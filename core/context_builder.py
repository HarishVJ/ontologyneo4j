"""
Context builder: transforms Neo4j KPI recipe + extracted terms
into a compact structured context for the LLM SQL generator.
"""

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


def build_context(extraction: ExtractionResult, recipe: KPIRecipe) -> StructuredContext:
    """Build structured LLM context from extraction result and KPI recipe."""
    settings = get_settings()

    # Resolve view metadata
    views_data = []
    for view_name in recipe.views:
        meta = get_view_metadata(view_name)
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
                "name": view_name,
                "alias": view_name[0].lower(),
                "columns": [],
                "schema": settings.snowflake_schema_prefix,
                "approved_aliases": [],
            })

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
