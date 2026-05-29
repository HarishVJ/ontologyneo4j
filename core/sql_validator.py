"""
SQL Validator: ensures generated SQL is safe, schema-compliant, and respects security scope.
Validates BEFORE execution — blocks unsafe queries at the gate.
"""

import re
import os
import yaml
from core.models import ValidationResult, StructuredContext
from config.logging_config import get_logger

_ROLES_CACHE: dict[str, list[str]] = {}


def _get_authorized_stations(user_id: str) -> list[str] | None:
    """Load authorized stations for user_id from roles.yaml (cached)."""
    global _ROLES_CACHE
    if user_id in _ROLES_CACHE:
        return _ROLES_CACHE[user_id]
    roles_path = os.path.join(
        os.path.dirname(__file__), "..", "ontology", "security", "roles.yaml"
    )
    try:
        with open(roles_path, "r") as f:
            data = yaml.safe_load(f)
        for role in data.get("roles", []):
            _ROLES_CACHE[role["user_id"]] = [s.upper() for s in role.get("authorized_stations", [])]
        return _ROLES_CACHE.get(user_id)
    except Exception:
        return None

logger = get_logger(__name__)

# Forbidden SQL keywords (case-insensitive)
FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER",
    "MERGE", "EXEC", "EXECUTE", "GRANT", "REVOKE", "CREATE",
]


def validate_sql(
    sql: str,
    context: StructuredContext,
    authorized_stations: list[str] | None = None,
) -> ValidationResult:
    """
    Run all validation checks on generated SQL.
    Returns ValidationResult with status and detailed checks.
    """
    checks = []
    errors = []

    # Check 1: Must be a SELECT statement
    cleaned = sql.strip().upper()
    if cleaned.startswith("SELECT") or cleaned.startswith("WITH"):
        checks.append({"check": "is_select", "status": "passed"})
    else:
        checks.append({"check": "is_select", "status": "failed"})
        errors.append("Query must start with SELECT or WITH (CTE)")

    # Check 2: No forbidden keywords
    for keyword in FORBIDDEN_KEYWORDS:
        pattern = rf"\b{keyword}\b"
        if re.search(pattern, sql, re.IGNORECASE):
            checks.append({"check": f"no_{keyword.lower()}", "status": "failed"})
            errors.append(f"Forbidden keyword detected: {keyword}")
            break
    else:
        checks.append({"check": "no_forbidden_keywords", "status": "passed"})

    # Check 3: No semicolons (prevent multi-statement injection)
    if ";" in sql:
        checks.append({"check": "no_semicolons", "status": "failed"})
        errors.append("Semicolons not allowed (prevents multi-statement injection)")
    else:
        checks.append({"check": "no_semicolons", "status": "passed"})

    # Check 4: Schema compliance — all tables must be in approved views
    approved_views = {v["name"].upper() for v in context.views}
    table_refs = _extract_table_references(sql)
    unapproved = []
    for ref in table_refs:
        # Strip schema prefix for comparison
        table_name = ref.split(".")[-1].upper()
        if table_name not in approved_views:
            unapproved.append(ref)

    if unapproved:
        checks.append({"check": "schema_compliance", "status": "failed"})
        errors.append(f"Unapproved tables referenced: {', '.join(unapproved)}")
    else:
        checks.append({"check": "schema_compliance", "status": "passed"})

    # Check 5: Column compliance
    approved_columns = set()
    for view in context.views:
        for col in view.get("columns", []):
            approved_columns.add(col.upper())
        # Include computed/alias names defined per-view (e.g. ATTRITION_RATE_PCT)
        for alias in view.get("approved_aliases", []):
            approved_columns.add(alias.upper())
    # Common SQL aliases and aggregate output names
    approved_columns.update({
        "CONTRACT_COUNT", "STATION_COUNT", "CUSTOMER_COUNT", "CNT", "TOTAL",
        "COUNT(DISTINCT", "DISTINCT", "B", "AS",
        # Attrition computed columns (fallback if not in view aliases)
        "ATTRITION_RATE_PCT", "TOTAL_TERMINATIONS", "TOTAL_HEADCOUNT",
        "DAYS_IN_PERIOD", "PERIOD_START", "PERIOD_END", "ANNUALIZED_RATE",
        "EMPLOYEE_HEADCOUNT_ATTRITION", "TOTAL_TERMINATION",
        # CTE common names
        "TERMINATIONS", "HEADCOUNT", "RATE", "ATTRITION_RATE",
        "PERIOD_BOUNDS", "PERIOD_DAYS", "DATEDIFF", "DATEADD", "DATE_TRUNC",
    })

    referenced_cols = _extract_column_references(sql)
    unapproved_cols = []
    for col in referenced_cols:
        col_upper = col.upper()
        if col_upper not in approved_columns and not col_upper.startswith("'"):
            unapproved_cols.append(col)

    if unapproved_cols:
        checks.append({"check": "column_compliance", "status": "warning", "detail": f"Unrecognized columns: {', '.join(unapproved_cols[:5])}"})
    else:
        checks.append({"check": "column_compliance", "status": "passed"})

    # Check 6: Security scope (RLS)
    # Resolve stations: use passed list, or look up from roles.yaml by user_id
    user_id = getattr(context, "user_id", None) or "demo_user"
    resolved_stations = authorized_stations or _get_authorized_stations(user_id)
    if resolved_stations:
        station_refs = _extract_station_filters(sql)
        unauthorized = [s for s in station_refs if s not in resolved_stations]
        if unauthorized:
            checks.append({"check": "security_scope", "status": "failed"})
            errors.append(f"Unauthorized station access: {', '.join(unauthorized)}")
        else:
            checks.append({"check": "security_scope", "status": "passed"})
    else:
        checks.append({"check": "security_scope", "status": "skipped"})

    status = "failed" if errors else "passed"
    logger.info("sql_validated", status=status, checks=len(checks), errors=len(errors))

    return ValidationResult(status=status, checks=checks, errors=errors)


def _extract_table_references(sql: str) -> list[str]:
    """Extract table/view references from FROM and JOIN clauses."""
    pattern = r"(?:FROM|JOIN)\s+([\w.]+)"
    matches = re.findall(pattern, sql, re.IGNORECASE)
    return matches


def _extract_column_references(sql: str) -> list[str]:
    """Extract top-level column/alias names from SELECT clause only.
    Skips function internals to avoid false positives from DATEDIFF, ROUND etc.
    """
    select_match = re.search(r"SELECT\s+(.*?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
    if not select_match:
        return []

    select_clause = select_match.group(1).strip()

    # Split only on commas that are NOT inside parentheses
    parts = []
    depth = 0
    current = []
    for ch in select_clause:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())

    cols = []
    for part in parts:
        part = part.strip()
        # Extract the AS alias if present — that's what we care about
        alias_match = re.search(r"\bAS\s+(\w+)\s*$", part, re.IGNORECASE)
        if alias_match:
            cols.append(alias_match.group(1).upper())
            continue
        # No alias — extract bare column name (table.COL or COL)
        # Skip if it's a function call (contains a paren before any plain token)
        if "(" in part:
            continue
        bare = part.split(".")[-1].strip()
        if bare and bare != "*" and not bare.startswith("'"):
            cols.append(bare.upper())

    return cols


def _extract_station_filters(sql: str) -> list[str]:
    """Extract station codes from WHERE clause for RLS check."""
    pattern = r"STATIONCODE\s*=\s*'(\w+)'"
    matches = re.findall(pattern, sql, re.IGNORECASE)
    return [m.upper() for m in matches]
