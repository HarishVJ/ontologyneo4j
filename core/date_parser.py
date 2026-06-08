"""
Robust natural-language date/period parser.
Converts phrases like 'Dec '25', 'Q4 2025', 'last 6 months' into
column-agnostic Snowflake SQL with {date_col} placeholders.
"""

import re

_MONTH_NAMES = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def _parse_month_year(phrase: str) -> str | None:
    match = re.search(
        r"\b(january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|"
        r"august|aug|september|sep|sept|october|oct|november|nov|december|dec)"
        r"\s*'?\s*(\d{2,4})\b",
        phrase,
        re.IGNORECASE,
    )
    if not match:
        return None
    month_name = match.group(1).lower()
    year_str = match.group(2)
    month = _MONTH_NAMES[month_name]
    year = int(year_str)
    if year < 100:
        year += 2000 if year < 50 else 1900
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end_year, end_month = year + 1, 1
    else:
        end_year, end_month = year, month + 1
    end = f"{end_year:04d}-{end_month:02d}-01"
    return f"{{date_col}} >= '{start}' AND {{date_col}} < '{end}'"


def _parse_quarter_year(phrase: str) -> str | None:
    match = re.search(r"\bq([1-4])\s*'?\s*(\d{2,4})\b", phrase, re.IGNORECASE)
    if not match:
        return None
    q = int(match.group(1))
    year_str = match.group(2)
    year = int(year_str)
    if year < 100:
        year += 2000 if year < 50 else 1900
    start_month = (q - 1) * 3 + 1
    end_month = start_month + 3
    end_year = year
    if end_month > 12:
        end_month -= 12
        end_year += 1
    start = f"{year:04d}-{start_month:02d}-01"
    end = f"{end_year:04d}-{end_month:02d}-01"
    return f"{{date_col}} >= '{start}' AND {{date_col}} < '{end}'"


def _parse_relative(phrase: str) -> str | None:
    phrase_lower = phrase.lower()

    # this month / current month
    if re.search(r"\b(this|current)\s+month\b", phrase_lower):
        return "{date_col} >= DATE_TRUNC('month', CURRENT_DATE)"

    # last month / previous month
    if re.search(r"\b(last|previous)\s+month\b", phrase_lower):
        return (
            "{date_col} >= DATEADD(month, -1, DATE_TRUNC('month', CURRENT_DATE)) "
            "AND {date_col} < DATE_TRUNC('month', CURRENT_DATE)"
        )

    # this year / ytd / year to date
    if re.search(r"\b(this\s+year|ytd|year\s+to\s+date)\b", phrase_lower):
        return "{date_col} >= DATE_TRUNC('year', CURRENT_DATE)"

    # last year
    if re.search(r"\blast\s+year\b", phrase_lower):
        return "{date_col} >= DATE_TRUNC('year', DATEADD(year, -1, CURRENT_DATE))"

    # this quarter / qtd
    if re.search(r"\b(this\s+quarter|qtd|quarter\s+to\s+date)\b", phrase_lower):
        return "{date_col} >= DATE_TRUNC('quarter', CURRENT_DATE)"

    # last quarter / previous quarter
    if re.search(r"\b(last|previous)\s+quarter\b", phrase_lower):
        return (
            "{date_col} >= DATEADD(quarter, -1, DATE_TRUNC('quarter', CURRENT_DATE)) "
            "AND {date_col} < DATE_TRUNC('quarter', CURRENT_DATE)"
        )

    # last N days / months / years / quarters
    match = re.search(
        r"\blast\s+(\d+)\s+(day|days|month|months|year|years|quarter|quarters)\b",
        phrase_lower,
    )
    if match:
        n = int(match.group(1))
        unit = match.group(2)
        if unit in ("day", "days"):
            return f"{{date_col}} >= DATEADD(day, -{n}, CURRENT_DATE)"
        elif unit in ("month", "months"):
            return f"{{date_col}} >= DATEADD(month, -{n}, CURRENT_DATE)"
        elif unit in ("year", "years"):
            return f"{{date_col}} >= DATEADD(year, -{n}, CURRENT_DATE)"
        elif unit in ("quarter", "quarters"):
            return f"{{date_col}} >= DATEADD(quarter, -{n}, CURRENT_DATE)"

    # mtd
    if re.search(r"\bmtd\b", phrase_lower):
        return "{date_col} >= DATE_TRUNC('month', CURRENT_DATE)"

    return None


def _parse_year(phrase: str) -> str | None:
    match = re.search(r"\b(20\d{2})\b", phrase)
    if match:
        year = int(match.group(1))
        start = f"{year}-01-01"
        end = f"{year + 1}-01-01"
        return f"{{date_col}} >= '{start}' AND {{date_col}} < '{end}'"
    return None


def parse_period(phrase: str) -> str | None:
    """
    Parse a natural language date/period phrase into a Snowflake SQL filter
    with a {date_col} placeholder. Returns None if the phrase is not recognized.
    """
    for parser in (_parse_month_year, _parse_quarter_year, _parse_relative, _parse_year):
        sql = parser(phrase)
        if sql:
            return sql
    return None


def parse_time_grouping(phrase: str) -> str | None:
    """
    Detect time-grain grouping phrases like 'by month', 'monthly', 'trend by quarter'.
    Returns a GROUP BY expression with {date_col} placeholder, or None.
    """
    phrase_lower = phrase.lower()
    grains = [
        (r"\b(by\s+month|monthly|per\s+month|trend\s+by\s+month)\b", "month"),
        (r"\b(by\s+quarter|quarterly|per\s+quarter|trend\s+by\s+quarter)\b", "quarter"),
        (r"\b(by\s+year|yearly|annual|per\s+year|trend\s+by\s+year)\b", "year"),
        (r"\b(by\s+week|weekly|per\s+week|trend\s+by\s+week)\b", "week"),
    ]
    for pat, grain in grains:
        if re.search(pat, phrase_lower):
            return f"DATE_TRUNC('{grain}', {{date_col}})"
    return None
