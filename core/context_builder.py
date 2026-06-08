"""
Context builder: transforms Neo4j KPI recipe + extracted terms
into a compact structured context for the LLM SQL generator.
Fully generic: filter emission and rejection are driven by ontology metadata.
"""

import yaml
from pathlib import Path

from core.models import (
    ExtractionResult,
    KPIRecipe,
    StructuredContext,
    ViewMetadata,
)
from core.ontology_lookup import get_view_metadata, get_joins_between_views
from config.settings import get_settings
from config.logging_config import get_logger

logger = get_logger(__name__)

# ─── Authoritative view registry from views.yaml ───────────────────────────
_VIEWS_YAML = Path(__file__).resolve().parent.parent / "ontology" / "schema" / "views.yaml"
_VIEW_REGISTRY: dict[str, dict] = {}

# Friendly labels for term categories (used in rejection messages)
_CATEGORY_LABELS = {
    "stations": "station",
    "customers": "customer",
    "regions": "region",
    "divisions": "division",
    "entities": "legal entity",
    "costcenter": "cost center",
    "attrition_period": "time period",
    "sub_regions": "sub-region",
    "service_types": "line of service",
    "departments": "department",
    "cities": "city",
    "states": "state",
    "postal_codes": "postal code",
    "employment_status": "employment status",
    "employment_type": "employment type",
    "pay_code": "pay code",
}


def _load_view_registry() -> None:
    """Load views.yaml into a local registry (called once at import)."""
    global _VIEW_REGISTRY
    try:
        with open(_VIEWS_YAML) as f:
            data = yaml.safe_load(f)
        for view in data.get("views", []):
            name = view["name"]
            _VIEW_REGISTRY[name.upper()] = {
                "name": name,
                "schema": view.get("schema", ""),
                "alias": view.get("alias", ""),
                "columns": [c["name"] for c in view.get("columns", [])],
                "approved_aliases": view.get("approved_aliases", []),
                "date_column": view.get("date_column"),
                "unsupported_term_categories": view.get("unsupported_term_categories", []),
            }
        logger.info("view_registry_loaded", count=len(_VIEW_REGISTRY))
    except Exception as e:
        logger.error("view_registry_load_failed", error=str(e))


_load_view_registry()


def _resolve_view_name(neo4j_name: str) -> str:
    """Resolve a view name from Neo4j against the authoritative YAML registry."""
    upper = neo4j_name.upper()
    if upper in _VIEW_REGISTRY:
        return _VIEW_REGISTRY[upper]["name"]
    for canonical_upper, view_data in _VIEW_REGISTRY.items():
        if canonical_upper.startswith(upper) and canonical_upper != upper:
            logger.warning(
                "view_name_resolved_from_registry",
                neo4j_name=neo4j_name,
                canonical_name=view_data["name"],
            )
            return view_data["name"]
    return neo4j_name


def _build_filter(term, date_column: str | None = None) -> str | None:
    """Emit a filter SQL fragment based on term.value_kind.
    value_kind: code | canonical -> column = 'value'
    value_kind: sql_expr          -> append value directly (pre-built SQL)
    {date_col} placeholders are bound to the view's date_column if provided.
    """
    if not term.column and term.value_kind != "sql_expr":
        return None

    if term.value_kind == "sql_expr":
        sql = term.value
        # Bind generic {date_col} placeholder
        if date_column and "{date_col}" in sql:
            sql = sql.replace("{date_col}", date_column)
        # Legacy: attrition_period terms used hardcoded DATE column
        elif term.category == "attrition_period" and date_column and "DATE" in sql:
            sql = sql.replace("DATE", date_column)
        return sql

    # code | canonical | default -> equality filter
    return f"{term.column} = '{term.value}'"


def build_context(extraction: ExtractionResult, recipe: KPIRecipe) -> StructuredContext:
    """Build structured LLM context from extraction result and KPI recipe."""
    settings = get_settings()

    # ── 1. Resolve view metadata ────────────────────────────────────────────
    views_data = []
    resolved_view_names = []
    all_unsupported: set[str] = set()
    date_columns: dict[str, str | None] = {}

    for view_name in recipe.views:
        canonical_name = _resolve_view_name(view_name)
        resolved_view_names.append(canonical_name)

        reg = _VIEW_REGISTRY.get(canonical_name.upper())
        if reg:
            views_data.append({
                "name": reg["name"],
                "alias": reg["alias"],
                "columns": reg["columns"],
                "schema": reg["schema"],
                "approved_aliases": reg.get("approved_aliases", []),
            })
            date_columns[canonical_name] = reg.get("date_column")
            all_unsupported.update(reg.get("unsupported_term_categories", []))
        else:
            meta = get_view_metadata(canonical_name)
            if meta:
                views_data.append({
                    "name": meta.name,
                    "alias": meta.alias,
                    "columns": meta.columns,
                    "schema": meta.schema,
                    "approved_aliases": meta.approved_aliases,
                })
                date_columns[canonical_name] = meta.date_column
                all_unsupported.update(meta.unsupported_term_categories)
            else:
                views_data.append({
                    "name": canonical_name,
                    "alias": canonical_name[0].lower(),
                    "columns": [],
                    "schema": settings.snowflake_schema_prefix,
                    "approved_aliases": [],
                })
                date_columns[canonical_name] = None

    # ── 2. Metadata-driven explicit rejection ───────────────────────────────
    supported = set(recipe.supported_term_categories)
    if supported:
        unsupported_detected = [
            t for t in extraction.detected_terms.values()
            if t.category not in supported
        ]
        if unsupported_detected:
            labels = sorted(set(
                _CATEGORY_LABELS.get(t.category, t.category.replace("_", " "))
                for t in unsupported_detected
            ))
            dims = ", ".join(labels)
            raise ValueError(
                f"{recipe.name} data is only available at a limited set of dimensions. "
                f"Filtering by {dims} is not supported. "
                f"Try a query using the supported dimensions instead."
            )

    # Also reject terms that the view itself declares unsupported
    if all_unsupported:
        view_unsupported = [
            t for t in extraction.detected_terms.values()
            if t.category in all_unsupported
        ]
        if view_unsupported:
            labels = sorted(set(
                _CATEGORY_LABELS.get(t.category, t.category.replace("_", " "))
                for t in view_unsupported
            ))
            dims = ", ".join(labels)
            raise ValueError(
                f"The data source for {recipe.name} does not include {dims} information. "
                f"Try a different query or KPI."
            )

    # ── 3. Build generic filters from extracted terms ───────────────────────
    # Pick the primary date column from the first view that has one
    primary_date_col = next((c for c in date_columns.values() if c), None)
    filters = []

    # Group terms by category to emit IN(...) for multi-value queries
    terms_by_category: dict[str, list[DetectedTerm]] = {}
    for term in extraction.detected_terms.values():
        terms_by_category.setdefault(term.category, []).append(term)

    for cat, terms in terms_by_category.items():
        if len(terms) == 1:
            filt = _build_filter(terms[0], date_column=primary_date_col)
            if filt:
                filters.append(filt)
        else:
            # Multi-value: build IN clause for code/canonical categories
            if terms[0].value_kind == "sql_expr":
                for term in terms:
                    filt = _build_filter(term, date_column=primary_date_col)
                    if filt:
                        filters.append(filt)
            else:
                col = terms[0].column
                if col:
                    values = [f"'{t.value}'" for t in terms]
                    filters.append(f"{col} IN ({', '.join(values)})")

    # ── 4. Resolve joins for multi-view KPIs ────────────────────────────────
    joins = get_joins_between_views(resolved_view_names) if len(resolved_view_names) > 1 else []

    # ── 5. Build steps, grouping & limit ──────────────────────────────────
    steps = [f"Step {s.order}: {s.logic}" for s in recipe.steps]
    grouping = extraction.detected_grouping
    # Bind {date_col} placeholders in time-grouping expressions
    if primary_date_col:
        grouping = [
            g.replace("{date_col}", primary_date_col) if "{date_col}" in g else g
            for g in grouping
        ]
    limit = extraction.detected_limit

    # If top-N requested but no explicit order_by, inject recipe default
    order_by = recipe.output_shape.order_by if recipe.output_shape else []
    if limit and not order_by and recipe.default_ranking_metric:
        order_by = [f"{recipe.default_ranking_metric} {recipe.default_ranking_order}"]

    # Threshold filters (HAVING / WHERE depending on metric aggregation)
    threshold_filters = [t.sql_expr for t in extraction.detected_thresholds]

    context = StructuredContext(
        kpi_name=recipe.name,
        kpi_id=recipe.id,
        formula=recipe.formula,
        views=views_data,
        joins=joins,
        filters=filters,
        steps=steps,
        output_columns=recipe.output_shape.columns if recipe.output_shape else [],
        order_by=order_by,
        schema_prefix=settings.snowflake_schema_prefix,
        grouping=grouping,
        limit=limit,
        thresholds=threshold_filters,
    )

    logger.info(
        "context_built",
        kpi=recipe.name,
        filters=len(filters),
        views=len(views_data),
        joins=len(joins),
    )
    return context
