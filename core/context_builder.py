"""
Context builder: transforms Neo4j KPI recipe + extracted terms
into a compact structured context for the LLM SQL generator.
"""

import yaml
from pathlib import Path

from core.models import (
    ExtractionResult,
    KPIRecipe,
    StructuredContext,
    ViewMetadata,
)
from core.ontology_lookup import get_view_metadata
from config.settings import get_settings
from config.logging_config import get_logger

logger = get_logger(__name__)

# ─── Authoritative view registry from views.yaml ───────────────────────────
# This is the SINGLE SOURCE OF TRUTH for view names and metadata.
# If Neo4j returns a stale/old name, this registry overrides it.
_VIEWS_YAML = Path(__file__).resolve().parent.parent / "ontology" / "schema" / "views.yaml"
_VIEW_REGISTRY: dict[str, dict] = {}  # canonical_name → view dict


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
            }
        logger.info("view_registry_loaded", count=len(_VIEW_REGISTRY))
    except Exception as e:
        logger.error("view_registry_load_failed", error=str(e))


_load_view_registry()


def _resolve_view_name(neo4j_name: str) -> str:
    """Resolve a view name from Neo4j against the authoritative YAML registry.
    Returns the canonical name from views.yaml — fixes stale/renamed references.
    """
    upper = neo4j_name.upper()
    # Exact match
    if upper in _VIEW_REGISTRY:
        return _VIEW_REGISTRY[upper]["name"]
    # Prefix match: Neo4j has old truncated name, YAML has the full new name
    for canonical_upper, view_data in _VIEW_REGISTRY.items():
        if canonical_upper.startswith(upper) and canonical_upper != upper:
            logger.warning(
                "view_name_resolved_from_registry",
                neo4j_name=neo4j_name,
                canonical_name=view_data["name"],
            )
            return view_data["name"]
    # No match — return as-is
    return neo4j_name

# Columns that exist in AGGEMPCOUNT_ATTRITION_DATA_V_Table only
_ATTRITION_VIEW = "AGGEMPCOUNT_ATTRITION_DATA_V_Table"
_ATTRITION_SUPPORTED_FILTER_CATEGORIES = {"station", "costcenter", "attrition_period"}
_ATTRITION_UNSUPPORTED_LABELS = {
    "customer": "customer",
    "region": "region",
    "division": "division",
    "entity": "legal entity",
}


def build_context(extraction: ExtractionResult, recipe: KPIRecipe) -> StructuredContext:
    """Build structured LLM context from extraction result and KPI recipe."""
    settings = get_settings()

    # Resolve view metadata — views.yaml registry is authoritative for names
    views_data = []
    resolved_view_names = []
    for view_name in recipe.views:
        # Step 1: resolve the name from YAML registry (fixes stale Neo4j names)
        canonical_name = _resolve_view_name(view_name)
        resolved_view_names.append(canonical_name)

        # Step 2: try local YAML registry first (always up-to-date)
        reg = _VIEW_REGISTRY.get(canonical_name.upper())
        if reg:
            views_data.append({
                "name": reg["name"],
                "alias": reg["alias"],
                "columns": reg["columns"],
                "schema": reg["schema"],
                "approved_aliases": reg.get("approved_aliases", []),
            })
        else:
            # Fallback to Neo4j metadata
            meta = get_view_metadata(canonical_name)
            if meta:
                views_data.append({
                    "name": meta.name,
                    "alias": meta.alias,
                    "columns": meta.columns,
                    "schema": meta.schema,
                    "approved_aliases": meta.approved_aliases,
                })
            else:
                views_data.append({
                    "name": canonical_name,
                    "alias": canonical_name[0].lower(),
                    "columns": [],
                    "schema": settings.snowflake_schema_prefix,
                    "approved_aliases": [],
                })

    # Guard: attrition KPIs only support station/costcenter/period filters
    is_attrition_kpi = _ATTRITION_VIEW in resolved_view_names
    if is_attrition_kpi:
        unsupported = [
            _ATTRITION_UNSUPPORTED_LABELS[t.category]
            for t in extraction.detected_terms.values()
            if t.category in _ATTRITION_UNSUPPORTED_LABELS
        ]
        if unsupported:
            dims = ", ".join(sorted(set(unsupported)))
            raise ValueError(
                f"Attrition data is only available at station and cost-center level. "
                f"Filtering by {dims} is not supported. "
                f"Try: 'What is the attrition rate at MSP?' or "
                f"'Show attrition for cost center 641 YTD'."
            )

    # Build filter conditions from extracted terms
    filters = []
    for term_key, term in extraction.detected_terms.items():
        if term.column:
            if term.category == "costcenter":
                filters.append(f"{term.column} = '{term.value}'")
            elif term.category == "station":
                filters.append(f"STATIONCODE = '{term.value}'")
            elif term.category == "customer":
                filters.append(f"CUSTOMERNAME = '{term.value}'")
            elif term.category == "region":
                filters.append(f"GRANDPARENTREGIONNAME = '{term.value}'")
            elif term.category == "division":
                filters.append(f"DIVISIONNAME = '{term.value}'")
            elif term.category == "entity":
                filters.append(f"ENTITYDESCRIPTION = '{term.value}'")
            elif term.category == "attrition_period":
                filters.append(term.value)  # pre-built SQL date filter string

    # Build step descriptions
    steps = [f"Step {s.order}: {s.logic}" for s in recipe.steps]

    # Determine grouping from context
    grouping = extraction.detected_grouping

    context = StructuredContext(
        kpi_name=recipe.name,
        kpi_id=recipe.id,
        formula=recipe.formula,
        views=views_data,
        joins=[],  # Single view for contract hierarchy — no joins needed
        filters=filters,
        steps=steps,
        output_columns=recipe.output_shape.columns if recipe.output_shape else [],
        order_by=recipe.output_shape.order_by if recipe.output_shape else [],
        schema_prefix=settings.snowflake_schema_prefix,
        grouping=grouping,
    )

    logger.info(
        "context_built",
        kpi=recipe.name,
        filters=len(filters),
        views=len(views_data),
    )
    return context
