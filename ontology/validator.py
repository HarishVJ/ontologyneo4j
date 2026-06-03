"""
Ontology structural validator.
Runs cheap completeness checks against the seeded Neo4j graph and the
source YAML files. Designed to fail fast if the ontology is wired up
incorrectly before the runtime pipeline tries to use it.
"""

import yaml
from pathlib import Path
from core.neo4j_client import execute_query
from config.logging_config import get_logger

logger = get_logger(__name__)
ONTOLOGY_DIR = Path(__file__).resolve().parent


def validate_ontology() -> dict:
    """Return {passed, warnings, failed, overall} after running checks."""
    results = {"passed": [], "warnings": [], "failed": []}

    # Check 1 — at least one active metric
    metrics = execute_query(
        "MATCH (m:Metric {status: 'active'}) RETURN count(m) AS cnt"
    )
    cnt = metrics[0]["cnt"] if metrics else 0
    if cnt > 0:
        results["passed"].append(f"Active metrics: {cnt}")
    else:
        results["failed"].append("No active metrics found")

    # Check 2 — every metric points at exactly one primary view
    orphans = execute_query(
        "MATCH (m:Metric) WHERE NOT (m)-[:USES_VIEW]->(:View) RETURN m.id AS id"
    )
    if orphans:
        results["failed"].append(
            f"Metrics without USES_VIEW: {[r['id'] for r in orphans]}"
        )
    else:
        results["passed"].append("All metrics linked to a view")

    # Check 3 — every metric has at least one sliceable dimension
    no_dims = execute_query(
        """
        MATCH (m:Metric)
        WHERE NOT (m)-[:SLICEABLE_BY]->(:Dimension)
        RETURN m.id AS id
        """
    )
    if no_dims:
        results["warnings"].append(
            f"Metrics with no sliceable_by dimensions: {[r['id'] for r in no_dims]}"
        )
    else:
        results["passed"].append("All metrics declare sliceable_by dimensions")

    # Check 4 — `kind: metric` requires expression and alias; `kind: list`
    # requires list_columns
    bad_kinds = execute_query(
        """
        MATCH (m:Metric)
        WHERE (m.kind = 'metric' AND (m.expression IS NULL OR m.expression = '' OR m.alias IS NULL OR m.alias = ''))
           OR (m.kind = 'list'   AND (m.list_columns IS NULL OR size(m.list_columns) = 0))
        RETURN m.id AS id, m.kind AS kind
        """
    )
    if bad_kinds:
        results["failed"].append(
            f"Metrics with incomplete shape for their kind: {bad_kinds}"
        )
    else:
        results["passed"].append("All metric kinds have required fields")

    # Check 5 — every view has columns
    empty = execute_query(
        "MATCH (v:View) WHERE coalesce(v.column_count, 0) = 0 RETURN v.name AS name"
    )
    if empty:
        results["warnings"].append(
            f"Views with no columns: {[r['name'] for r in empty]}"
        )
    else:
        results["passed"].append("All views have columns")

    # Check 6 — sliceable_by dimensions either live on the primary view
    # or are reachable via a Join.PROVIDES edge from a JOINS_TO neighbour
    unreachable = execute_query(
        """
        MATCH (m:Metric)-[:USES_VIEW]->(start:View),
              (m)-[:SLICEABLE_BY]->(d:Dimension)
        WHERE NOT EXISTS { (start)-[:PROVIDES]->(d) }
          AND NOT EXISTS {
              MATCH path = (start)-[:JOINS_TO*1..3]->(:View)
              WHERE ANY(rel IN relationships(path)
                        WHERE EXISTS {
                            MATCH (j:Join {id: rel.join_id})-[:PROVIDES]->(d)
                        })
              RETURN path
          }
          AND NOT EXISTS {
              MATCH (start)-[:JOINS_TO*1..3]->(end:View)-[:PROVIDES]->(d)
              RETURN end
          }
        RETURN m.id AS metric, d.name AS dim
        """
    )
    if unreachable:
        results["warnings"].append(
            f"Sliceable dimensions with no resolvable join path: "
            f"{[(r['metric'], r['dim']) for r in unreachable]}"
        )
    else:
        results["passed"].append("All sliceable_by dimensions reachable")

    # Check 7 — at least one join edge defined
    j_cnt = execute_query("MATCH ()-[r:JOINS_TO]->() RETURN count(r) AS cnt")
    j = j_cnt[0]["cnt"] if j_cnt else 0
    if j > 0:
        results["passed"].append(f"Join edges: {j}")
    else:
        results["warnings"].append("No JOINS_TO edges — multi-view queries will not work")

    # Check 8 — entity term categories non-empty
    cat = execute_query(
        "MATCH (t:Term) WHERE t.category <> 'metric_synonym' "
        "RETURN t.category AS cat, count(t) AS cnt ORDER BY cnt DESC"
    )
    for r in cat:
        results["passed"].append(f"Term category '{r['cat']}': {r['cnt']} entries")

    # Check 9 — YAML metric files all parse and have unique IDs.
    # Each file may hold either a single metric document or a list under
    # the top-level `metrics:` key.
    seen: set[str] = set()
    duplicates: list[str] = []
    for f in sorted((ONTOLOGY_DIR / "metrics").glob("*.yaml")):
        with open(f) as fh:
            doc = yaml.safe_load(fh) or {}
        if isinstance(doc, dict) and "metrics" in doc:
            metrics_in_file = doc.get("metrics") or []
        else:
            metrics_in_file = [doc] if isinstance(doc, dict) and doc else []

        for m in metrics_in_file:
            if not isinstance(m, dict):
                continue
            mid = m.get("id")
            if not mid:
                results["failed"].append(
                    f"Metric in {f.name} is missing required `id`"
                )
                continue
            if mid in seen:
                duplicates.append(mid)
            seen.add(mid)
    if duplicates:
        results["failed"].append(f"Duplicate metric IDs in YAML: {duplicates}")
    else:
        results["passed"].append(f"YAML metric files: {len(seen)} unique IDs")

    overall = "FAILED" if results["failed"] else "PASSED"
    results["overall"] = overall
    logger.info(
        "ontology_validated",
        overall=overall,
        passed=len(results["passed"]),
        failed=len(results["failed"]),
        warnings=len(results["warnings"]),
    )
    return results
