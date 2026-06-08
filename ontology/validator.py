"""
Ontology structural validator.
Checks completeness before the pipeline uses the graph.
"""

import json
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

    # Check 9: All TermCategory nodes loaded
    tc_count = execute_query(
        "MATCH (tc:TermCategory) RETURN count(tc) AS cnt"
    )
    tcc = tc_count[0]["cnt"] if tc_count else 0
    if tcc > 0:
        results["passed"].append(f"Term categories: {tcc}")
    else:
        results["failed"].append("No TermCategory nodes found — extractor has no metadata")

    # Check 10: Extractable categories that need a column have one
    missing_col = execute_query(
        "MATCH (tc:TermCategory)<-[:IN_CATEGORY]-(t:Term) "
        "WHERE tc.extractable = true AND tc.value_kind <> 'sql_expr' "
        "  AND t.category <> 'kpi_synonyms' "
        "  AND (t.column IS NULL OR t.column = '') "
        "RETURN t.category AS cat, t.code AS code"
    )
    if missing_col:
        items = [f"{r['cat']}.{r['code']}" for r in missing_col]
        results["failed"].append(f"Terms missing column mapping: {items}")
    else:
        results["passed"].append("All extractable terms have column mappings")

    # Check 11: KPI supported_term_categories reference real categories
    bad_cats = execute_query(
        "MATCH (k:KPI) "
        "UNWIND k.supported_term_categories AS sc "
        "WITH k, sc WHERE sc <> '' AND NOT EXISTS { MATCH (tc:TermCategory {name: sc}) } "
        "RETURN k.name AS kpi, sc AS bad_cat"
    )
    if bad_cats:
        for r in bad_cats:
            results["warnings"].append(
                f"KPI '{r['kpi']}' references unknown term category '{r['bad_cat']}'"
            )
    else:
        results["passed"].append("All KPI supported_term_categories valid")

    # Check 12: Views with period-using KPIs declare date_column
    no_date_col = execute_query(
        "MATCH (k:KPI)-[:USES_VIEW]->(v:View) "
        "WHERE k.supported_term_categories IS NOT NULL "
        "  AND 'attrition_period' IN k.supported_term_categories "
        "  AND (v.date_column IS NULL OR v.date_column = '') "
        "RETURN k.name AS kpi, v.name AS view"
    )
    if no_date_col:
        for r in no_date_col:
            results["failed"].append(
                f"KPI '{r['kpi']}' uses period filter but view '{r['view']}' has no date_column"
            )
    else:
        results["passed"].append("All period-enabled views have date_column")

    # Check 13: KPI dimension metadata is structurally valid
    kpi_metadata = execute_query(
        "MATCH (k:KPI) "
        "OPTIONAL MATCH (k)-[:USES_VIEW]->(v:View) "
        "RETURN k.name AS kpi, k.grain AS grain, k.dimension_rules_json AS dimension_rules_json, "
        "k.required_context_json AS required_context_json, collect(DISTINCT v.columns) AS view_columns"
    )
    missing_grain = []
    bad_dimension_refs = []
    bad_dimension_columns = []
    unsupported_without_reason = []
    missing_prompts = []
    known_categories = {
        r["name"]
        for r in execute_query("MATCH (tc:TermCategory) RETURN tc.name AS name")
    }
    for row in kpi_metadata:
        kpi_name = row["kpi"]
        grain = row.get("grain") or []
        if not grain:
            missing_grain.append(kpi_name)
        try:
            dimension_rules = json.loads(row.get("dimension_rules_json") or "{}")
        except json.JSONDecodeError:
            results["failed"].append(f"KPI '{kpi_name}' has invalid dimension_rules_json")
            dimension_rules = {}
        try:
            required_context = json.loads(row.get("required_context_json") or "{}")
        except json.JSONDecodeError:
            results["failed"].append(f"KPI '{kpi_name}' has invalid required_context_json")
            required_context = {}

        available_columns = set()
        for columns in row.get("view_columns", []):
            available_columns.update(columns or [])

        for category, rule in dimension_rules.items():
            if category not in known_categories:
                bad_dimension_refs.append(f"{kpi_name}.{category}")
            if not isinstance(rule, dict):
                continue
            if rule.get("support_type") == "unsupported" and not rule.get("reason"):
                unsupported_without_reason.append(f"{kpi_name}.{category}")
            if rule.get("support_type") == "native":
                column = rule.get("column")
                if column and column not in available_columns:
                    bad_dimension_columns.append(f"{kpi_name}.{category}->{column}")

        for field, requirement in required_context.items():
            if (
                isinstance(requirement, dict)
                and requirement.get("required", False)
                and not requirement.get("clarification_prompt")
            ):
                missing_prompts.append(f"{kpi_name}.{field}")

    if missing_grain:
        results["warnings"].append(f"KPIs without explicit grain metadata: {missing_grain}")
    else:
        results["passed"].append("All KPIs have explicit grain metadata")
    if bad_dimension_refs:
        results["failed"].append(f"KPI dimension rules reference unknown term categories: {bad_dimension_refs}")
    else:
        results["passed"].append("All KPI dimension rules reference valid term categories")
    if bad_dimension_columns:
        results["failed"].append(f"Native dimension columns missing from KPI views: {bad_dimension_columns}")
    else:
        results["passed"].append("All native KPI dimension columns exist in linked views")
    if unsupported_without_reason:
        results["warnings"].append(f"Unsupported dimensions without reason: {unsupported_without_reason}")
    else:
        results["passed"].append("All unsupported dimensions include reasons")
    if missing_prompts:
        results["failed"].append(f"Required context entries missing clarification prompts: {missing_prompts}")
    else:
        results["passed"].append("All required context entries have clarification prompts")

    overall = "PASSED" if not results["failed"] else "FAILED"
    results["overall"] = overall
    logger.info("ontology_validated", overall=overall, passed=len(results["passed"]),
                failed=len(results["failed"]), warnings=len(results["warnings"]))
    return results
