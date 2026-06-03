"""
Lean Ontology Loader: reads YAML files and seeds Neo4j with the
semantic graph used at runtime by the plan extractor and SQL composer.

YAML is the source of truth. Neo4j is a queryable projection rebuilt
from scratch on every run (DETACH DELETE + MERGE).

Graph model
-----------
Nodes:
    :Metric       — id, kind (metric|list), name, description, expression,
                    alias, unit, list_columns, distinct_on, default_order_by,
                    date_column, view (primary), synonyms, example_questions,
                    version, status, owner
    :View         — name, schema, alias, description, columns, approved_aliases
    :Column       — name, type, description
    :Dimension    — name (column name used for slicing/grouping)
    :Term         — code, canonical, category, column, aliases, expression
    :Join         — id, on, type, description

Relationships:
    (:Metric)-[:USES_VIEW]->(:View)
    (:Metric)-[:SLICEABLE_BY]->(:Dimension)
    (:Metric)-[:HAS_SYNONYM]->(:Term)
    (:View)-[:HAS_COLUMN]->(:Column)
    (:View)-[:PROVIDES]->(:Dimension)        # column directly on the view
    (:View)-[:JOINS_TO {join_id, on, type}]->(:View)
    (:Join)-[:PROVIDES]->(:Dimension)        # dimensions exposed via this join
"""

import yaml
from pathlib import Path
from core.neo4j_client import get_driver
from config.logging_config import get_logger

logger = get_logger(__name__)
ONTOLOGY_DIR = Path(__file__).resolve().parent


def load_all() -> dict[str, int]:
    """Load every YAML in the ontology folder into Neo4j. Idempotent."""
    counts: dict[str, int] = {}
    _clear_ontology()
    _ensure_constraints()
    counts["views"] = _load_views()
    counts["joins"] = _load_joins()
    counts["metrics"] = _load_metrics()
    counts["terms"] = _load_terms()
    counts["roles"] = _load_roles()
    logger.info("ontology_loaded", **counts)
    return counts


# ─── Maintenance ────────────────────────────────────────────────────────


def _clear_ontology() -> None:
    driver = get_driver()
    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    logger.info("ontology_cleared")


def _ensure_constraints() -> None:
    driver = get_driver()
    statements = [
        "CREATE CONSTRAINT metric_id_unique IF NOT EXISTS FOR (m:Metric) REQUIRE m.id IS UNIQUE",
        "CREATE CONSTRAINT view_name_unique IF NOT EXISTS FOR (v:View) REQUIRE v.name IS UNIQUE",
        "CREATE CONSTRAINT dim_name_unique IF NOT EXISTS FOR (d:Dimension) REQUIRE d.name IS UNIQUE",
        "CREATE CONSTRAINT join_id_unique IF NOT EXISTS FOR (j:Join) REQUIRE j.id IS UNIQUE",
        "CREATE INDEX term_code IF NOT EXISTS FOR (t:Term) ON (t.code)",
        "CREATE INDEX metric_kind IF NOT EXISTS FOR (m:Metric) ON (m.kind)",
    ]
    with driver.session() as s:
        for stmt in statements:
            s.run(stmt)
    logger.info("ontology_constraints_ensured")


# ─── Loaders ────────────────────────────────────────────────────────────


def _load_views() -> int:
    """Load views and their columns. Each column also becomes a :Dimension
    node connected to the view via :PROVIDES so the join-path query can
    discover columns reachable from a starting view."""
    with open(ONTOLOGY_DIR / "views.yaml") as f:
        data = yaml.safe_load(f)
    driver = get_driver()
    count = 0
    with driver.session() as session:
        for view in data.get("views", []):
            columns = view.get("columns", [])
            column_names = [c["name"] for c in columns]
            session.run(
                """
                MERGE (v:View {name: $name})
                SET v.schema = $schema,
                    v.alias = $alias,
                    v.description = $desc,
                    v.columns = $columns,
                    v.column_count = $cc,
                    v.approved_aliases = $aliases
                """,
                {
                    "name": view["name"],
                    "schema": view.get("schema", ""),
                    "alias": view.get("alias", ""),
                    "desc": view.get("description", ""),
                    "columns": column_names,
                    "cc": len(column_names),
                    "aliases": view.get("approved_aliases", []),
                },
            )
            for col in columns:
                session.run(
                    """
                    MATCH (v:View {name: $vname})
                    MERGE (c:Column {name: $cname, view: $vname})
                    SET c.type = $ctype, c.description = $cdesc
                    MERGE (v)-[:HAS_COLUMN]->(c)
                    MERGE (d:Dimension {name: $cname})
                    MERGE (v)-[:PROVIDES]->(d)
                    """,
                    {
                        "vname": view["name"],
                        "cname": col["name"],
                        "ctype": col.get("type", ""),
                        "cdesc": col.get("description", ""),
                    },
                )
            count += 1
    logger.info("views_loaded", count=count)
    return count


def _load_joins() -> int:
    """Load joins as both :Join nodes (for `provides` semantics) and
    JOINS_TO edges between views (for shortest-path queries)."""
    with open(ONTOLOGY_DIR / "joins.yaml") as f:
        data = yaml.safe_load(f)
    driver = get_driver()
    count = 0
    with driver.session() as session:
        for join in data.get("joins", []):
            session.run(
                """
                MERGE (j:Join {id: $id})
                SET j.on = $on, j.type = $type, j.description = $desc,
                    j.from = $from, j.to = $to
                """,
                {
                    "id": join["id"],
                    "on": join.get("on", ""),
                    "type": join.get("type", "INNER"),
                    "desc": join.get("description", ""),
                    "from": join["from"],
                    "to": join["to"],
                },
            )
            session.run(
                """
                MATCH (fv:View {name: $from}), (tv:View {name: $to})
                MERGE (fv)-[r:JOINS_TO {join_id: $id}]->(tv)
                SET r.on = $on, r.type = $type
                """,
                {
                    "from": join["from"],
                    "to": join["to"],
                    "id": join["id"],
                    "on": join.get("on", ""),
                    "type": join.get("type", "INNER"),
                },
            )
            for dim in join.get("provides", []):
                session.run(
                    """
                    MERGE (d:Dimension {name: $dim})
                    WITH d
                    MATCH (j:Join {id: $jid})
                    MERGE (j)-[:PROVIDES]->(d)
                    """,
                    {"dim": dim, "jid": join["id"]},
                )
            count += 1
    logger.info("joins_loaded", count=count)
    return count


def _load_metrics() -> int:
    """Load every metric YAML in ontology/metrics/. Each file may hold
    either a single metric document (top-level `id:`) or a list of
    metrics under a top-level `metrics:` key."""
    metrics_dir = ONTOLOGY_DIR / "metrics"
    driver = get_driver()
    count = 0
    for yaml_file in sorted(metrics_dir.glob("*.yaml")):
        with open(yaml_file) as f:
            doc = yaml.safe_load(f) or {}
        # Accept either {metrics: [...]} or a single metric document.
        if isinstance(doc, dict) and "metrics" in doc:
            metrics_in_file = doc.get("metrics") or []
        else:
            metrics_in_file = [doc] if isinstance(doc, dict) and doc else []

        for m in metrics_in_file:
            if not m or not m.get("id"):
                logger.warning(
                    "metric_skipped_no_id",
                    file=yaml_file.name,
                )
                continue
            count += _persist_metric(driver, m)
    logger.info("metrics_loaded", count=count)
    return count


def _persist_metric(driver, m: dict) -> int:
    """MERGE one metric into the graph along with USES_VIEW, SLICEABLE_BY,
    and HAS_SYNONYM relationships. Returns 1 on success."""
    with driver.session() as session:
        session.run(
            """
            MERGE (m:Metric {id: $id})
            SET m.kind = $kind,
                m.name = $name,
                m.description = $desc,
                m.expression = $expr,
                m.alias = $alias,
                m.unit = $unit,
                m.polarity = $polarity,
                m.view = $view,
                m.date_column = $dcol,
                m.list_columns = $lcols,
                m.distinct_on = $don,
                m.default_order_by = $dob,
                m.example_questions = $eq,
                m.version = $ver,
                m.status = $status,
                m.owner = $owner
            """,
            {
                "id": m["id"],
                "kind": m.get("kind", "metric"),
                "name": m.get("name", ""),
                "desc": m.get("description", ""),
                "expr": m.get("expression", ""),
                "alias": m.get("alias", ""),
                "unit": m.get("unit", ""),
                "polarity": m.get("polarity", ""),
                "view": m.get("view", ""),
                "dcol": m.get("date_column", ""),
                "lcols": m.get("list_columns", []) or [],
                "don": m.get("distinct_on", "") or "",
                "dob": m.get("default_order_by", []) or [],
                "eq": m.get("example_questions", []) or [],
                "ver": m.get("version", "1.0"),
                "status": m.get("status", "active"),
                "owner": m.get("owner", ""),
            },
        )
        if m.get("view"):
            session.run(
                """
                MATCH (m:Metric {id: $id}), (v:View {name: $view})
                MERGE (m)-[:USES_VIEW]->(v)
                """,
                {"id": m["id"], "view": m["view"]},
            )
        for dim in m.get("sliceable_by", []) or []:
            session.run(
                """
                MERGE (d:Dimension {name: $dim})
                WITH d
                MATCH (m:Metric {id: $id})
                MERGE (m)-[:SLICEABLE_BY]->(d)
                """,
                {"dim": dim, "id": m["id"]},
            )
        for syn in m.get("synonyms", []) or []:
            session.run(
                """
                MERGE (t:Term {code: $code, category: 'metric_synonym'})
                SET t.canonical = $canonical, t.metric_id = $id
                WITH t
                MATCH (m:Metric {id: $id})
                MERGE (m)-[:HAS_SYNONYM]->(t)
                """,
                {"code": syn, "canonical": m.get("name", syn), "id": m["id"]},
            )
    return 1


def _load_terms() -> int:
    """Load entity vocabulary (stations, customers, regions, periods, …).
    `aliases` and `expression` are stored as properties for use by the
    plan extractor when resolving user-typed values."""
    with open(ONTOLOGY_DIR / "terms.yaml") as f:
        data = yaml.safe_load(f)
    driver = get_driver()
    count = 0
    with driver.session() as session:
        for category in data.get("categories", []):
            cat_name = category["name"]
            cat_column = category.get("column")
            for term in category.get("terms", []):
                session.run(
                    """
                    MERGE (t:Term {code: $code, category: $cat})
                    SET t.canonical = $canonical,
                        t.column = $col,
                        t.aliases = $aliases,
                        t.expression = $expr
                    """,
                    {
                        "code": term["code"],
                        "cat": cat_name,
                        "canonical": term.get("canonical", term["code"]),
                        "col": cat_column,
                        "aliases": term.get("aliases", []) or [],
                        "expr": term.get("expression", "") or "",
                    },
                )
                count += 1
    logger.info("terms_loaded", count=count)
    return count


def _load_roles() -> int:
    """Load user → authorized stations/customers as :User nodes for RLS."""
    roles_file = ONTOLOGY_DIR / "security" / "roles.yaml"
    if not roles_file.exists():
        logger.warning("roles_skipped", reason="file not found")
        return 0
    with open(roles_file) as f:
        data = yaml.safe_load(f)
    driver = get_driver()
    count = 0
    with driver.session() as session:
        for role in data.get("roles", []):
            session.run(
                """
                MERGE (u:User {user_id: $uid})
                SET u.email = $email,
                    u.authorized_stations = $stations,
                    u.authorized_customers = $customers,
                    u.description = $desc
                """,
                {
                    "uid": role["user_id"],
                    "email": role.get("email", ""),
                    "stations": role.get("authorized_stations", []),
                    "customers": role.get("authorized_customers", []),
                    "desc": role.get("description", ""),
                },
            )
            count += 1
    logger.info("roles_loaded", count=count)
    return count
