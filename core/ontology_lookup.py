"""
Neo4j ontology lookup — retrieves KPI recipes from the graph.
Returns structured recipe data for the context builder.
"""

import json
from core.neo4j_client import execute_query
from core.models import KPIRecipe, KPIStep, KPIFilter, OutputShape, ViewMetadata
from config.logging_config import get_logger

logger = get_logger(__name__)


def lookup_kpi(kpi_name: str) -> KPIRecipe | None:
    """Fetch a complete KPI recipe from Neo4j by name."""
    records = execute_query(
        """
        MATCH (k:KPI {name: $name, status: 'active'})
        OPTIONAL MATCH (k)-[:REQUIRES_STEP]->(s:KPIStep)
        OPTIONAL MATCH (k)-[:HAS_FILTER]->(f:Filter)
        OPTIONAL MATCH (k)-[:USES_VIEW]->(v:View)
        RETURN k {.*} AS kpi,
               collect(DISTINCT s {.*}) AS steps,
               collect(DISTINCT f {.*}) AS filters,
               collect(DISTINCT v.name) AS views
        """,
        {"name": kpi_name},
    )

    if not records or not records[0].get("kpi"):
        logger.warning("kpi_not_found", kpi_name=kpi_name)
        return None

    row = records[0]
    kpi_data = row["kpi"]

    steps = [
        KPIStep(
            order=s.get("order", 0),
            name=s.get("name", ""),
            logic=s.get("logic", ""),
            required_columns=s.get("required_columns", []),
        )
        for s in sorted(row.get("steps", []), key=lambda x: x.get("order", 0))
    ]

    filters = [
        KPIFilter(
            column=f.get("column", ""),
            source=f.get("source", ""),
            operator=f.get("operator", "="),
        )
        for f in row.get("filters", [])
    ]

    output_data = kpi_data.get("output_shape_type")
    output_shape = OutputShape(
        type=output_data or "list",
        columns=kpi_data.get("output_columns", []),
        order_by=kpi_data.get("order_by", []),
    )
    dimension_rules = json.loads(kpi_data.get("dimension_rules_json") or "{}")
    required_context = json.loads(kpi_data.get("required_context_json") or "{}")

    recipe = KPIRecipe(
        id=kpi_data.get("id", ""),
        name=kpi_data.get("name", ""),
        description=kpi_data.get("description", ""),
        complexity=kpi_data.get("complexity", "simple"),
        formula=kpi_data.get("formula", ""),
        views=row.get("views", []),
        steps=steps,
        filters=filters,
        output_shape=output_shape,
        supported_term_categories=kpi_data.get("supported_term_categories", []),
        default_ranking_metric=kpi_data.get("default_ranking_metric"),
        default_ranking_order=kpi_data.get("default_ranking_order", "DESC"),
        version=kpi_data.get("version", "1.0"),
        status=kpi_data.get("status", "active"),
        grain=kpi_data.get("grain", []),
        dimension_rules=dimension_rules,
        required_context=required_context,
    )

    logger.info("kpi_recipe_loaded", kpi_name=kpi_name, steps=len(steps), views=len(recipe.views))
    return recipe


def get_view_metadata(view_name: str) -> ViewMetadata | None:
    """Fetch view metadata including columns from Neo4j."""
    records = execute_query(
        """
        MATCH (v:View {name: $name})
        RETURN v.name AS name, v.schema AS schema, v.alias AS alias,
               v.columns AS columns, v.approved_aliases AS approved_aliases,
               v.date_column AS date_column, v.unsupported_term_categories AS unsupported_term_categories
        """,
        {"name": view_name},
    )

    if not records:
        return None

    row = records[0]
    return ViewMetadata(
        name=row["name"],
        schema=row.get("schema", ""),
        alias=row.get("alias", ""),
        columns=row.get("columns", []),
        approved_aliases=row.get("approved_aliases", []),
        date_column=row.get("date_column"),
        unsupported_term_categories=row.get("unsupported_term_categories", []),
    )


def get_joins_between_views(view_names: list[str]) -> list[str]:
    """Fetch join conditions between the given views from Neo4j.
    Returns ordered join strings (e.g. 'INNER JOIN DIMFINANCEBUSINESSSTRUCTURE_V b ON ...').
    """
    if len(view_names) < 2:
        return []

    records = execute_query(
        """
        UNWIND $views AS view_name
        MATCH (v:View {name: view_name})
        WITH collect(v.name) AS view_set
        MATCH (fv:View)-[j:JOINS_TO]->(tv:View)
        WHERE fv.name IN view_set AND tv.name IN view_set
        RETURN j.type AS join_type, j.condition AS condition,
               fv.name AS from_view, fv.alias AS from_alias,
               tv.name AS to_view, tv.alias AS to_alias
        """,
        {"views": view_names},
    )

    joins = []
    for row in records:
        jtype = row.get("join_type", "INNER")
        cond = row.get("condition", "")
        to_alias = row.get("to_alias", "")
        to_view = row.get("to_view", "")
        if cond:
            joins.append(f"{jtype} JOIN {to_view} {to_alias} ON {cond}")

    return joins


def get_all_active_kpis() -> list[dict]:
    """Return summary of all active KPIs for help/discovery."""
    records = execute_query(
        """
        MATCH (k:KPI {status: 'active'})
        RETURN k.id AS id, k.name AS name, k.description AS description, k.complexity AS complexity
        ORDER BY k.name
        """
    )
    return records
