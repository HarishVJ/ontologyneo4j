"""
Intent + Term Extraction Module

Responsibility: FastAPI backend — rule-based KPI detection, term extraction,
and time period parsing from natural language questions.

Key Design: Term dictionary is loaded FROM Neo4j at startup.
Neo4j is the single source of truth — this module does NOT hardcode
what "ATL" means. It queries Neo4j once at startup to build a lookup table.

Component: Intent + Term Extraction
Owner: FastAPI Backend
"""

import os
import re
from datetime import date, timedelta
from dataclasses import dataclass
from typing import Optional
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()


@dataclass
class DetectedTerm:
    type: str
    value: str


@dataclass
class DetectedPeriod:
    type: str
    start_date: str
    end_date: str
    days_in_period: int


@dataclass
class ExtractionResult:
    detected_kpi: Optional[str]
    detected_terms: dict[str, DetectedTerm]
    detected_period: Optional[DetectedPeriod]


# KPI patterns — order matters (longer/more specific first)
KPI_PATTERNS = [
    (r"\battrition\s*rate\b", "Attrition Rate"),
    (r"\battrition\b", "Attrition Rate"),
    (r"\bturnover\s*rate\b", "Attrition Rate"),
    (r"\bturnover\b", "Attrition Rate"),
    (r"\bheadcount\b", "Headcount"),
    (r"\bhead\s*count\b", "Headcount"),
    (r"\bemployee\s*count\b", "Headcount"),
    (r"\bhc\b", "Headcount"),
    (r"\bovertime\s*%\b", "Overtime Percentage"),
    (r"\bot\s*%\b", "Overtime Percentage"),
    (r"\bovertime\b", "Overtime Percentage"),
    (r"\bfte\b", "FTE"),
]

# ─── Term Dictionary (loaded from Neo4j at startup) ────────────
# These sets are populated by load_terms_from_neo4j().
# Neo4j is the single source of truth for ALL term knowledge.
STATIONS: set[str] = set()
CUSTOMERS: set[str] = set()
KPI_NAMES: dict[str, str] = {}  # lowercase term → canonical KPI name
_terms_loaded = False


def load_terms_from_neo4j():
    """
    Query Neo4j for all Term nodes and KPI names, building lookup sets.
    Called once at application startup.
    """
    global STATIONS, CUSTOMERS, KPI_NAMES, _terms_loaded

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        # Load terms
        result = session.run(
            "MATCH (t:Term) RETURN t.code AS code, t.category AS category, t.canonical AS canonical"
        )
        for record in result:
            code = record["code"]
            category = record["category"]
            if category == "stations":
                STATIONS.add(code)
            elif category == "customers":
                CUSTOMERS.add(code)
            elif category == "kpi_names":
                KPI_NAMES[code.lower()] = record["canonical"]

        # Load KPI names directly from KPI nodes
        kpi_result = session.run("MATCH (k:KPI) RETURN k.name AS name")
        for record in kpi_result:
            name = record["name"]
            KPI_NAMES[name.lower()] = name

    driver.close()
    _terms_loaded = True
    print(f"   ✓ Intent extractor loaded from Neo4j: "
          f"{len(STATIONS)} stations, {len(CUSTOMERS)} customers, "
          f"{len(KPI_NAMES)} KPI terms")

# Period patterns
PERIOD_PATTERNS = [
    (r"\blast\s*month\b", "last_month"),
    (r"\bprevious\s*month\b", "last_month"),
    (r"\bthis\s*month\b", "this_month"),
    (r"\bcurrent\s*month\b", "this_month"),
    (r"\blast\s*quarter\b", "last_quarter"),
    (r"\bytd\b", "year_to_date"),
    (r"\byear\s*to\s*date\b", "year_to_date"),
]


def _resolve_period(period_type: str) -> DetectedPeriod:
    """Convert a period type into concrete date range."""
    today = date.today()

    if period_type == "last_month":
        first_of_this_month = today.replace(day=1)
        end_date = first_of_this_month - timedelta(days=1)
        start_date = end_date.replace(day=1)
    elif period_type == "this_month":
        start_date = today.replace(day=1)
        end_date = today
    elif period_type == "last_quarter":
        quarter = (today.month - 1) // 3
        if quarter == 0:
            start_date = date(today.year - 1, 10, 1)
            end_date = date(today.year - 1, 12, 31)
        else:
            start_month = (quarter - 1) * 3 + 1
            start_date = date(today.year, start_month, 1)
            end_month = quarter * 3
            if end_month == 12:
                end_date = date(today.year, 12, 31)
            else:
                end_date = date(today.year, end_month + 1, 1) - timedelta(days=1)
    elif period_type == "year_to_date":
        start_date = date(today.year, 1, 1)
        end_date = today
    else:
        start_date = today.replace(day=1)
        end_date = today

    days = (end_date - start_date).days + 1
    return DetectedPeriod(
        type=period_type,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        days_in_period=days,
    )


def extract(question: str) -> ExtractionResult:
    """
    Extract intent (KPI), terms (stations, customers), and time period
    from a natural language question.

    Term lookup uses dictionaries loaded from Neo4j at startup.
    """
    if not _terms_loaded:
        load_terms_from_neo4j()
    q_lower = question.lower()
    q_upper = question.upper()

    # 1. Detect KPI (regex patterns first, then Neo4j-loaded KPI terms)
    detected_kpi = None
    for pattern, kpi_name in KPI_PATTERNS:
        if re.search(pattern, q_lower):
            detected_kpi = kpi_name
            break
    # Fallback: check Neo4j-loaded KPI synonym dictionary
    if not detected_kpi and KPI_NAMES:
        # Sort by length descending so longer phrases match first
        for term, canonical in sorted(KPI_NAMES.items(), key=lambda x: len(x[0]), reverse=True):
            if term in q_lower:
                detected_kpi = canonical
                break

    # 2. Detect terms (stations, customers)
    detected_terms = {}
    words = re.findall(r"\b[A-Za-z0-9]+\b", question)
    for word in words:
        upper_word = word.upper()
        if upper_word in STATIONS:
            detected_terms[upper_word] = DetectedTerm(type="station", value=upper_word)
        elif upper_word in CUSTOMERS:
            detected_terms[upper_word] = DetectedTerm(type="customer", value=upper_word)

    # 3. Detect period
    detected_period = None
    for pattern, period_type in PERIOD_PATTERNS:
        if re.search(pattern, q_lower):
            detected_period = _resolve_period(period_type)
            break

    return ExtractionResult(
        detected_kpi=detected_kpi,
        detected_terms=detected_terms,
        detected_period=detected_period,
    )
