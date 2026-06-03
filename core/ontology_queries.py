"""
Cypher queries that the runtime pipeline issues against the seeded
ontology graph. These are the only Neo4j calls the pipeline makes.

    Q1  fetch_metric_catalog        — for the plan extractor LLM
    Q2  fetch_view_meta             — view + columns for a metric
    Q3  resolve_join_chain          — shortest path from a metric's
                                       primary view to a target dimension
    Q4  resolve_term                — entity vocabulary lookup
"""

from core.neo4j_client import execute_query
from core.models import JoinChain, JoinHop, ViewMeta
from config.logging_config import get_logger

logger = get_logger(__name__)

_CATALOG_CACHE: list[dict] | None = None
_TERMS_CACHE: list[dict] | None = None


# ─── Q1 — Metric catalog (cached, refreshed on seed) ──────────────────


def fetch_metric_catalog(refresh: bool = False) -> list[dict]:
    """Return one record per metric with everything the plan extractor
    needs to choose a metric and infer its slots."""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None and not refresh:
        return _CATALOG_CACHE

    records = execute_query(
        """
        MATCH (m:Metric {status: 'active'})
        OPTIONAL MATCH (m)-[:USES_VIEW]->(v:View)
        OPTIONAL MATCH (m)-[:SLICEABLE_BY]->(d:Dimension)
        OPTIONAL MATCH (m)-[:HAS_SYNONYM]->(t:Term)
        RETURN
            m.id                    AS id,
            m.kind                  AS kind,
            m.name                  AS name,
            m.description           AS description,
            m.expression            AS expression,
            m.alias                 AS alias,
            m.unit                  AS unit,
            m.polarity              AS polarity,
            m.list_columns          AS list_columns,
            m.distinct_on           AS distinct_on,
            m.default_order_by      AS default_order_by,
            m.date_column           AS date_column,
            m.example_questions     AS example_questions,
            v.name                  AS view,
            collect(DISTINCT d.name) AS sliceable_by,
            collect(DISTINCT t.code) AS synonyms
        ORDER BY m.id
        """
    )
    _CATALOG_CACHE = records
    logger.info("metric_catalog_fetched", count=len(records))
    return records


def clear_catalog_cache() -> None:
    global _CATALOG_CACHE, _TERMS_CACHE
    _CATALOG_CACHE = None
    _TERMS_CACHE = None


# ─── Q2 — View metadata (alias, schema, columns) ──────────────────────


def fetch_view_meta(view_name: str) -> ViewMeta | None:
    records = execute_query(
        """
        MATCH (v:View {name: $name})
        RETURN v.name AS name, v.schema AS schema, v.alias AS alias,
               v.columns AS columns, v.approved_aliases AS approved_aliases
        """,
        {"name": view_name},
    )
    if not records:
        return None
    r = records[0]
    return ViewMeta(
        name=r["name"],
        schema=r.get("schema") or "",
        alias=r.get("alias") or view_name[0].lower(),
        columns=r.get("columns") or [],
        approved_aliases=r.get("approved_aliases") or [],
    )


# ─── Q3 — Join-path discovery (the killer query) ──────────────────────


def resolve_join_chain(metric_id: str, dim_name: str) -> JoinChain:
    """Return a JoinChain from the metric's primary view to the target
    dimension. Empty `hops` means the dimension lives on the primary
    view itself. If no path exists, returns an empty chain (caller must
    decide to error or fallback)."""

    # Fast path — dimension is directly on the primary view
    direct = execute_query(
        """
        MATCH (m:Metric {id: $mid})-[:USES_VIEW]->(v:View)-[:PROVIDES]->(d:Dimension {name: $dim})
        RETURN v.name AS view
        LIMIT 1
        """,
        {"mid": metric_id, "dim": dim_name},
    )
    if direct:
        return JoinChain(target_dimension=dim_name, hops=[], end_view=direct[0]["view"])

    # Search shortest JOINS_TO path of length 1..3 where either an edge's
    # join provides the dim or the terminal view provides it.
    paths = execute_query(
        """
        MATCH (m:Metric {id: $mid})-[:USES_VIEW]->(start:View)
        MATCH path = (start)-[rels:JOINS_TO*1..3]->(end:View)
        WHERE EXISTS { (end)-[:PROVIDES]->(:Dimension {name: $dim}) }
           OR ANY(r IN rels WHERE EXISTS {
                 MATCH (j:Join {id: r.join_id})-[:PROVIDES]->(:Dimension {name: $dim})
              })
        WITH path, length(path) AS L
        ORDER BY L ASC
        LIMIT 1
        RETURN
            [n IN nodes(path) | n.name] AS view_chain,
            [r IN relationships(path) | { join_id: r.join_id, on: r.on, type: r.type }] AS edges
        """,
        {"mid": metric_id, "dim": dim_name},
    )

    if not paths:
        logger.warning("join_chain_not_found", metric=metric_id, dim=dim_name)
        return JoinChain(target_dimension=dim_name, hops=[], end_view="")

    row = paths[0]
    view_chain: list[str] = row["view_chain"]
    edges: list[dict] = row["edges"]

    hops: list[JoinHop] = []
    for i, e in enumerate(edges):
        hops.append(
            JoinHop(
                join_id=e["join_id"],
                on=e.get("on", ""),
                type=e.get("type", "INNER"),
                from_view=view_chain[i],
                to_view=view_chain[i + 1],
            )
        )
    return JoinChain(target_dimension=dim_name, hops=hops, end_view=view_chain[-1])


# ─── Q4 — Term resolution (entity vocabulary) ─────────────────────────


def fetch_terms(refresh: bool = False) -> list[dict]:
    """Return all terms grouped by category, used to seed the plan
    extractor's prompt with the available entity vocabulary."""
    global _TERMS_CACHE
    if _TERMS_CACHE is not None and not refresh:
        return _TERMS_CACHE

    records = execute_query(
        """
        MATCH (t:Term)
        WHERE t.category <> 'metric_synonym'
        RETURN t.category   AS category,
               t.code       AS code,
               t.canonical  AS canonical,
               t.column     AS column,
               t.aliases    AS aliases,
               t.expression AS expression
        ORDER BY t.category, t.code
        """
    )
    _TERMS_CACHE = records
    logger.info("terms_fetched", count=len(records))
    return records


def fetch_authorized_stations(user_id: str) -> list[str]:
    rows = execute_query(
        "MATCH (u:User {user_id: $uid}) RETURN coalesce(u.authorized_stations, []) AS stations",
        {"uid": user_id},
    )
    return rows[0]["stations"] if rows else []
