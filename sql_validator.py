"""
SQL Validator Module

Responsibility: Validate generated SQL for safety, schema compliance,
approved views/columns, and security scope enforcement.

Component: SQL Validator
Owner: Python Backend Validation Layer
"""

import re
from typing import Optional


# Destructive SQL keywords that must never appear
BLOCKED_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "MERGE", "DROP",
    "TRUNCATE", "ALTER", "CREATE", "GRANT", "REVOKE",
    "EXEC", "EXECUTE",
]

# Approved views
APPROVED_VIEWS = {
    "DIMHISTORYEMPLOYEE_V",
    "DIMFINANCEBUSINESSSTRUCTURE_V",
    "FACTDAILYWORKDETAILS_MS_V",
    "DIMJOBTYPE_V",
    "DIMSERVICETYPE_V",
    "DIMEMPLOYEETYPE_V",
    "DIMEMPLOYMENTSTATUS_V",
    "DIMEMPLOYMENTSTATUS_HR_V",
    "DIMEMPLOYMENTTYPE_V",
    "AGGEMPCOUNT_ATTRITION_DATA_V",
    "AGGRHOURS_ACTUALHOURS_DETAILS_V",
    "AGGEMPCOUNT_PAY_28DAYS_V",
    "DIMRLSCONTRACTHIERARCHY_V",
}

# Approved columns (all known columns across views)
APPROVED_COLUMNS = {
    "EMPLOYEE_ID", "FIRSTNAME", "LASTNAME", "FULLNAME", "HIREDATE",
    "EMPLOYMENTSTATUSCODE", "EMPLOYMENTTYPECODE", "EMPLOYEETYPECODE",
    "PAYCLASSCODE", "COSTCENTER", "DEPARTMENTCODE", "LOCATIONCODE",
    "JOBTYPECODE", "STATIONCODE", "CUSTOMERCODE", "SERVICETYPECODE",
    "TERMINATIONDATE", "MANAGERID", "COMPANYCODE", "DIVISIONCODE",
    "GRANDPARENTREGIONCODE", "GRANDPARENTREGIONNAME", "REGIONCODE",
    "REGIONNAME", "ENTITYCODE", "ENTITYDESCRIPTION", "DIVISIONNAME",
    "STATIONNAME", "CUSTOMERNAME", "SERVICETYPENAME", "CONTRACTCODE",
    "CONTRACTNAME", "DEPARTMENTNAME", "DISPLAYNAME", "ENTITY_STATION",
    "PUNCHID", "APPLYDATE", "PAYCODE_CODE", "PUNCH_HOURS",
    "CREATEDDATE", "UPDATEDDATE", "ORIGINAL_TRANSDATE",
    "EMPLOYEE_COSTCENTER", "WITH_PAY_FLAG", "DATE",
    "HISTORYEMPLOYEE_EMPLOYMENTTYPECODE", "HISTORYEMPLOYEE_PAYCLASSCODE",
    "EMPLOYEE_HEADCOUNT_ATTRITION", "TOTAL_TERMINATION",
    "PAYCODE_DESCRIPTION", "SUBREGIONCODE", "SUBREGIONNAME",
    "PARENTREGIONCODE", "PARENTREGIONNAME", "DEPARTMENTID",
    # Computed aliases (common in CTEs)
    "CNT", "HEADCOUNT", "ATTRITION_RATE", "TOTAL_TERMINATIONS",
    "TOTAL_HEADCOUNT", "LAST_PUNCH_DATE",
}


class SQLValidator:
    """Validates generated SQL for safety and schema compliance."""

    def validate(
        self,
        sql: str,
        allowed_columns: list[str],
        station_filter: Optional[str] = None,
        security_scope: Optional[dict] = None,
    ) -> dict:
        """
        Validate SQL and return structured result with check details.

        Returns:
            {"status": "passed"|"failed", "checks": [...], "errors": [...]}
        """
        if not sql:
            return {"status": "failed", "checks": [], "errors": ["No SQL provided"]}

        checks = []
        errors = []
        sql_upper = sql.upper()

        # Check 1: SELECT-only
        # Allow WITH (CTEs) at start too
        first_keyword = sql_upper.strip().split()[0] if sql_upper.strip() else ""
        if first_keyword in ("SELECT", "WITH"):
            checks.append("SELECT-only query")
        else:
            errors.append(f"Query starts with '{first_keyword}' — not a SELECT statement")

        # Check 2: No destructive keywords
        found_blocked = []
        for kw in BLOCKED_KEYWORDS:
            # Match as whole word
            if re.search(rf"\b{kw}\b", sql_upper):
                found_blocked.append(kw)
        if not found_blocked:
            checks.append("No INSERT, UPDATE, DELETE, MERGE, DROP, TRUNCATE, ALTER")
        else:
            errors.append(f"Blocked keywords found: {', '.join(found_blocked)}")

        # Check 3: Approved views only
        # Extract table/view references after FROM and JOIN
        view_pattern = r"(?:FROM|JOIN)\s+(?:AIRCO_EDW_UAT\.ILINKAICHAT\.)?(\w+)"
        referenced_views = set(re.findall(view_pattern, sql_upper))
        # Filter out CTE names (they appear in WITH ... AS)
        cte_pattern = r"(\w+)\s+AS\s*\("
        cte_names = set(re.findall(cte_pattern, sql_upper))
        referenced_views -= cte_names
        unapproved = referenced_views - APPROVED_VIEWS
        if not unapproved:
            checks.append("Only approved views used")
        else:
            errors.append(f"Unapproved views: {', '.join(unapproved)}")

        # Check 4: Approved columns only
        # Extract column references (alias.COLUMN patterns, excluding schema prefixes)
        # Remove schema prefixes before analysis
        sql_clean = re.sub(r"AIRCO_EDW_UAT\.ILINKAICHAT\.", "", sql_upper)
        col_pattern = r"\b[A-Z]\w*\.(\w+)\b"
        referenced_cols = set(re.findall(col_pattern, sql_clean))
        # Remove view names that appear after schema (they're table names, not columns)
        referenced_cols -= APPROVED_VIEWS
        # Filter: only check things that look like column names (not SQL keywords/literals)
        sql_keywords = {
            "SELECT", "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER",
            "CROSS", "GROUP", "ORDER", "HAVING", "LIMIT", "OFFSET", "UNION",
            "DISTINCT", "COUNT", "SUM", "AVG", "MAX", "MIN", "CASE", "WHEN",
            "THEN", "ELSE", "END", "AND", "NOT", "NULL", "BETWEEN", "LIKE",
            "EXISTS", "WITH", "NULLIF", "ROUND", "DATEADD", "DATEDIFF",
            "COALESCE", "CAST", "DATE", "DAY", "MONTH", "YEAR",
        }
        # Common CTE/alias names that are safe
        common_aliases = {"CNT", "HEADCOUNT", "ATTRITION_RATE", "TOTAL_TERMINATIONS",
                         "TOTAL_HEADCOUNT", "LAST_PUNCH_DATE", "SALARIED_TERMINATIONS",
                         "HOURLY_TERMINATIONS", "JOB_ABANDONMENT", "ACTIVE_HEADCOUNT",
                         "LEAVE_SUSPENDED_HEADCOUNT", "EMPLOYEE_SCOPE", "LAST_PUNCH",
                         "FINAL_CALC", "MAX_APPLYDATE", "TOTALS"}
        actual_cols = referenced_cols - sql_keywords - cte_names - common_aliases
        bad_cols = actual_cols - APPROVED_COLUMNS
        if not bad_cols:
            checks.append("Only approved columns used")
        else:
            errors.append(f"Unapproved columns: {', '.join(bad_cols)}")

        # Check 5: Station filter present (if required)
        if station_filter:
            if station_filter in sql_upper:
                checks.append("Required station filter present")
            else:
                errors.append(f"Required station filter '{station_filter}' not found in SQL")

        # Check 6: Security scope validation
        if security_scope and station_filter:
            allowed_stations = [s.upper() for s in security_scope.get("stations", [])]
            if station_filter.upper() in allowed_stations:
                checks.append(f"Security scope validated: {station_filter} is allowed")
            else:
                errors.append(f"Security violation: {station_filter} not in user's allowed stations")

        # Check 7: No unauthorized table access
        if not unapproved:
            checks.append("No unauthorized table access")

        status = "passed" if not errors else "failed"
        result = {"status": status, "checks": checks}
        if errors:
            result["errors"] = errors
        return result
