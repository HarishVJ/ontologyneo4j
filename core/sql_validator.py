"""
SQL Validator — runs at the gate, before Snowflake execution.

Checks:
    1. Statement is SELECT or WITH (CTE)
    2. No forbidden DDL/DML keywords
    3. No semicolons (single-statement only)
    4. Every table/view referenced is in the View allowlist
    5. Every column referenced exists on some allowlisted view OR
       is a metric alias / approved alias produced by the composer
    6. Row-level security: no STATIONCODE filter outside the user's
       authorized stations
"""

import re
from core.models import ValidationResult, MetricSpec
from core.ontology_queries import fetch_view_meta, fetch_authorized_stations
from config.logging_config import get_logger

logger = get_logger(__name__)

FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER",
    "MERGE", "EXEC", "EXECUTE", "GRANT", "REVOKE", "CREATE",
]

# Common SQL idioms that may show up in the SELECT list / CTE bodies and
# should not be flagged as unknown columns.
_COMMON_TOKENS = {
    "DATEDIFF", "DATEADD", "DATE_TRUNC", "GREATEST", "LEAST", "NULLIF",
    "ROUND", "CAST", "COALESCE", "DISTINCT", "AS", "CASE", "WHEN", "THEN",
    "ELSE", "END", "AND", "OR", "NOT", "IN", "BETWEEN", "LIKE", "IS",
    "NULL", "TRUE", "FALSE", "ASC", "DESC", "NULLS", "LAST", "FIRST",
    "CURRENT_DATE", "CURRENT_TIMESTAMP", "MONTH", "YEAR", "DAY",
    "QUARTER", "WEEK", "B", "A", "E", "W", "_PREVIEW",
}


def validate_sql(
    sql: str,
    metric_specs: list[MetricSpec],
    user_id: str = "demo_user",
    authorized_stations: list[str] | None = None,
) -> ValidationResult:
    """Run all guardrails on the composed SQL. Returns a ValidationResult."""
    checks: list[dict[str, str]] = []
    errors: list[str] = []

    # ── 1. SELECT / WITH ────────────────────────────────────────────
    cleaned = sql.strip().upper()
    if cleaned.startswith("SELECT") or cleaned.startswith("WITH"):
        checks.append({"check": "is_select", "status": "passed"})
    else:
        checks.append({"check": "is_select", "status": "failed"})
        errors.append("Query must start with SELECT or WITH")

    # ── 2. No forbidden keywords ────────────────────────────────────
    forbidden_hit = None
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", sql, re.IGNORECASE):
            forbidden_hit = kw
            break
    if forbidden_hit:
        checks.append({"check": "no_forbidden_keywords", "status": "failed"})
        errors.append(f"Forbidden keyword detected: {forbidden_hit}")
    else:
        checks.append({"check": "no_forbidden_keywords", "status": "passed"})

    # ── 3. No semicolons ────────────────────────────────────────────
    if ";" in sql:
        checks.append({"check": "no_semicolons", "status": "failed"})
        errors.append("Semicolons not allowed (multi-statement protection)")
    else:
        checks.append({"check": "no_semicolons", "status": "passed"})

    # ── 4. View allowlist ───────────────────────────────────────────
    allowed_views, allowed_columns, allowed_aliases = _compute_allowlist(metric_specs)
    referenced_views = _extract_table_references(sql)
    unapproved = [
        ref for ref in referenced_views
        if ref.split(".")[-1].upper() not in allowed_views
    ]
    if unapproved:
        checks.append({"check": "schema_compliance", "status": "failed"})
        errors.append(f"Unapproved tables referenced: {', '.join(unapproved)}")
    else:
        checks.append({"check": "schema_compliance", "status": "passed"})

    # ── 5. Column compliance (advisory) ─────────────────────────────
    referenced_cols = _extract_select_aliases(sql)
    unknown = [
        c for c in referenced_cols
        if c.upper() not in allowed_columns
        and c.upper() not in allowed_aliases
        and c.upper() not in _COMMON_TOKENS
        and not c.startswith("'")
    ]
    if unknown:
        checks.append({
            "check": "column_compliance",
            "status": "warning",
            "detail": f"Unrecognized output names: {', '.join(unknown[:5])}",
        })
    else:
        checks.append({"check": "column_compliance", "status": "passed"})

    # ── 6. Row-level security ───────────────────────────────────────
    stations = authorized_stations or fetch_authorized_stations(user_id) or []
    if stations:
        used = _extract_station_filters(sql)
        unauthorized = [s for s in used if s not in {x.upper() for x in stations}]
        if unauthorized:
            checks.append({"check": "security_scope", "status": "failed"})
            errors.append(f"Unauthorized station access: {', '.join(unauthorized)}")
        else:
            checks.append({"check": "security_scope", "status": "passed"})
    else:
        checks.append({"check": "security_scope", "status": "skipped"})

    status = "failed" if errors else "passed"
    logger.info("sql_validated", status=status, errors=len(errors))
    return ValidationResult(status=status, checks=checks, errors=errors)


# ─── Helpers ──────────────────────────────────────────────────────────


def _compute_allowlist(specs: list[MetricSpec]) -> tuple[set[str], set[str], set[str]]:
    """Return (allowed_view_names, allowed_columns, allowed_aliases)."""
    views: set[str] = set()
    columns: set[str] = set()
    aliases: set[str] = set()

    for spec in specs:
        # primary view
        views.add(spec.view.name.upper())
        for c in spec.view.columns:
            columns.add(c.upper())
        for a in spec.view.approved_aliases:
            aliases.add(a.upper())
        if spec.alias:
            aliases.add(spec.alias.upper())

        # views reachable via join chains
        for chain in spec.join_chains.values():
            for hop in chain.hops:
                views.add(hop.to_view.upper())
                meta = fetch_view_meta(hop.to_view)
                if meta:
                    for c in meta.columns:
                        columns.add(c.upper())
                    for a in meta.approved_aliases:
                        aliases.add(a.upper())

    return views, columns, aliases


def _extract_table_references(sql: str) -> list[str]:
    pattern = r"(?:FROM|JOIN)\s+([\w.]+)"
    return re.findall(pattern, sql, re.IGNORECASE)


def _extract_select_aliases(sql: str) -> list[str]:
    """Extract top-level SELECT-clause aliases (e.g. `... AS FOO`)."""
    out: list[str] = []
    for m in re.finditer(r"SELECT\s+(.*?)\s+FROM", sql, re.IGNORECASE | re.DOTALL):
        body = m.group(1)
        # split on commas at depth 0
        depth = 0
        parts: list[str] = []
        cur: list[str] = []
        for ch in body:
            if ch == "(":
                depth += 1
                cur.append(ch)
            elif ch == ")":
                depth -= 1
                cur.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
        if cur:
            parts.append("".join(cur).strip())

        for p in parts:
            alias_m = re.search(r"\bAS\s+(\w+)\s*$", p, re.IGNORECASE)
            if alias_m:
                out.append(alias_m.group(1).upper())
                continue
            if "(" in p:
                continue
            bare = p.split(".")[-1].strip().rstrip(",")
            if bare and bare != "*" and not bare.startswith("'"):
                out.append(bare.upper())
    return out


def _extract_station_filters(sql: str) -> list[str]:
    pattern = r"STATIONCODE\s*=\s*'(\w+)'"
    return [m.upper() for m in re.findall(pattern, sql, re.IGNORECASE)]
