"""
Neo4j ontology lookup — retrieves KPI recipes from the graph.
Returns structured recipe data for the context builder.
"""

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
        version=kpi_data.get("version", "1.0"),
        status=kpi_data.get("status", "active"),
    )

    logger.info("kpi_recipe_loaded", kpi_name=kpi_name, steps=len(steps), views=len(recipe.views))
    return recipe


def get_view_metadata(view_name: str) -> ViewMetadata | None:
    """Fetch view metadata including columns from Neo4j."""
    records = execute_query(
        """
        MATCH (v:View {name: $name})
        RETURN v.name AS name, v.schema AS schema, v.alias AS alias, v.columns AS columns
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
    )


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
