"""
Ontology structural validator.
Checks completeness before the pipeline uses the graph.
"""

from core.neo4j_client import execute_query
from config.logging_config import get_logger

logger = get_logger(__name__)


def validate_ontology() -> dict:
    results = {"passed": [], "failed": [], "warnings": []}

    # Check 1: At least one active KPI exists
    kpis = execute_query("MATCH (k:KPI {status:'active'}) RETURN count(k) AS cnt")
    cnt = kpis[0]["cnt"] if kpis else 0
    if cnt > 0:
        results["passed"].append(f"Active KPIs: {cnt}")
    else:
        results["failed"].append("No active KPIs found")

    # Check 2: Every KPI has at least one step
    orphan_kpis = execute_query(
        "MATCH (k:KPI) WHERE NOT (k)-[:REQUIRES_STEP]->(:KPIStep) RETURN k.name AS name"
    )
    if orphan_kpis:
        names = [r["name"] for r in orphan_kpis]
        results["failed"].append(f"KPIs without steps: {names}")
    else:
        results["passed"].append("All KPIs have steps")

    # Check 3: Every KPI links to at least one view
    orphan_views = execute_query(
        "MATCH (k:KPI) WHERE NOT (k)-[:USES_VIEW]->(:View) RETURN k.name AS name"
    )
    if orphan_views:
        names = [r["name"] for r in orphan_views]
        results["failed"].append(f"KPIs without views: {names}")
    else:
        results["passed"].append("All KPIs linked to views")

    # Check 4: Views have columns
    empty_views = execute_query(
        "MATCH (v:View) WHERE v.column_count = 0 OR v.columns IS NULL RETURN v.name AS name"
    )
    if empty_views:
        names = [r["name"] for r in empty_views]
        results["warnings"].append(f"Views with no columns: {names}")
    else:
        results["passed"].append("All views have columns")

    # Check 5: KPI synonyms exist
    synonyms = execute_query(
        "MATCH (t:Term {category:'kpi_synonyms'}) RETURN count(t) AS cnt"
    )
    syn_cnt = synonyms[0]["cnt"] if synonyms else 0
    if syn_cnt > 0:
        results["passed"].append(f"KPI synonyms: {syn_cnt}")
    else:
        results["warnings"].append("No KPI synonyms found — intent extraction will fail")

    # Check 6: Term categories have entries
    cat_counts = execute_query(
        "MATCH (t:Term) RETURN t.category AS cat, count(t) AS cnt ORDER BY cnt DESC"
    )
    for r in cat_counts:
        results["passed"].append(f"Term category '{r['cat']}': {r['cnt']} entries")

    # Check 7: Join paths exist
    join_count = execute_query(
        "MATCH ()-[j:JOINS_TO]->() RETURN count(j) AS cnt"
    )
    j_cnt = join_count[0]["cnt"] if join_count else 0
    if j_cnt > 0:
        results["passed"].append(f"Join paths: {j_cnt}")
    else:
        results["warnings"].append("No join paths defined — multi-view queries will not work")

    # Check 8: Disambiguation rules exist
    disambig_count = execute_query(
        "MATCH (d:DisambiguationRule) RETURN count(d) AS cnt"
    )
    d_cnt = disambig_count[0]["cnt"] if disambig_count else 0
    if d_cnt > 0:
        results["passed"].append(f"Disambiguation rules: {d_cnt}")
    else:
        results["warnings"].append("No disambiguation rules — ambiguous terms may resolve incorrectly")

    overall = "PASSED" if not results["failed"] else "FAILED"
    results["overall"] = overall
    logger.info("ontology_validated", overall=overall, passed=len(results["passed"]),
                failed=len(results["failed"]), warnings=len(results["warnings"]))
    return results
