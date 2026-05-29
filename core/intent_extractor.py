"""
Intent extraction: detects KPI, terms (station, customer, region, division),
period, and aggregation modifiers from natural language questions.

All term knowledge is loaded from Neo4j at startup — no hardcoded values.
"""

import re
from core.models import ExtractionResult, DetectedTerm
from core.neo4j_client import execute_query
from config.logging_config import get_logger

logger = get_logger(__name__)

# Global term caches — populated from Neo4j
STATIONS: set[str] = set()
CUSTOMERS: dict[str, str] = {}  # lowercase name → canonical
REGIONS: dict[str, str] = {}
DIVISIONS: dict[str, str] = {}
ENTITIES: dict[str, str] = {}
KPI_SYNONYMS: dict[str, tuple[str, str]] = {}  # lowercase phrase → (canonical_name, kpi_id)
ATTRITION_PERIODS: dict[str, str] = {}  # lowercase phrase → SQL date filter string

_terms_loaded = False

# Period detection patterns
PERIOD_PATTERNS = [
    (r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s*'?\d{2,4}\b", "month_year"),
    (r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s*'?\d{2,4}\b", "month_year"),
    (r"\bq[1-4]\s*'?\d{2,4}\b", "quarter"),
    (r"\blast\s+(month|quarter|year|6\s*months|3\s*months)\b", "relative"),
    (r"\b(20\d{2})\b", "year"),
    (r"\b(ytd|year\s*to\s*date)\b", "ytd"),
    (r"\bcurrent\s+month\b", "current_month"),
]

# Aggregation modifiers
AGGREGATION_PATTERNS = [
    (r"\btop\s+(\d+)\b", "top_n"),
    (r"\bhighest\b", "max"),
    (r"\blowest\b", "min"),
    (r"\baverage\b", "avg"),
    (r"\btotal\b", "sum"),
]


def load_terms_from_neo4j() -> None:
    """Load all term categories from Neo4j into in-memory caches."""
    global STATIONS, CUSTOMERS, REGIONS, DIVISIONS, ENTITIES, KPI_SYNONYMS, ATTRITION_PERIODS, _terms_loaded

    try:
        records = execute_query(
            "MATCH (t:Term) RETURN t.code AS code, t.canonical AS canonical, "
            "t.category AS category, t.column AS column, t.kpi_id AS kpi_id, t.context AS context"
        )

        for r in records:
            code = r["code"]
            canonical = r["canonical"] or code
            category = r["category"]

            if category == "stations":
                STATIONS.add(code.upper())
            elif category == "customers":
                CUSTOMERS[code.lower()] = canonical
            elif category == "regions":
                REGIONS[code.lower()] = canonical
            elif category == "divisions":
                DIVISIONS[code.lower()] = canonical
            elif category == "entities":
                ENTITIES[code.lower()] = canonical
            elif category == "kpi_synonyms":
                kpi_id = r.get("kpi_id") or ""
                KPI_SYNONYMS[code.lower()] = (canonical, kpi_id)
            elif category == "attrition_period":
                # context field holds the SQL date filter expression
                sql_filter = r.get("context") or ""
                if sql_filter:
                    ATTRITION_PERIODS[code.lower()] = sql_filter

        _terms_loaded = True
        logger.info(
            "terms_loaded_from_neo4j",
            stations=len(STATIONS),
            customers=len(CUSTOMERS),
            regions=len(REGIONS),
            divisions=len(DIVISIONS),
            entities=len(ENTITIES),
            kpi_synonyms=len(KPI_SYNONYMS),
            attrition_periods=len(ATTRITION_PERIODS),
        )
    except Exception as e:
        logger.error("term_loading_failed", error=str(e))
        _terms_loaded = False


def extract(question: str) -> ExtractionResult:
    """Extract intent, terms, period, and modifiers from a natural language question."""
    if not _terms_loaded:
        load_terms_from_neo4j()

    q_lower = question.lower()
    result = ExtractionResult(original_question=question)

    # 1. Detect KPI — match longest synonym first
    if KPI_SYNONYMS:
        for phrase, (canonical, kpi_id) in sorted(
            KPI_SYNONYMS.items(), key=lambda x: len(x[0]), reverse=True
        ):
            if phrase in q_lower:
                result.detected_kpi = canonical
                result.detected_kpi_id = kpi_id
                break

    # 2. Detect stations (case-insensitive word match against uppercase codes)
    words = re.findall(r"\b[A-Za-z]{2,4}\b", question)
    for word in words:
        if word.upper() in STATIONS:
            result.detected_terms[word.upper()] = DetectedTerm(
                category="station", value=word.upper(), column="STATIONCODE"
            )
            break

    # 3. Detect customers (skip if a station was already matched on same token)
    detected_station_values = {t.value for t in result.detected_terms.values() if t.category == "station"}
    for name, canonical in sorted(CUSTOMERS.items(), key=lambda x: len(x[0]), reverse=True):
        if name in q_lower:
            # Avoid false match: don't match a customer whose name CONTAINS a matched station code
            if any(st in name.upper() for st in detected_station_values):
                continue
            # Require the match to be a word boundary (not a substring of a word)
            if re.search(rf"\b{re.escape(name)}\b", q_lower):
                result.detected_terms[canonical] = DetectedTerm(
                    category="customer", value=canonical, column="CUSTOMERNAME"
                )
                break

    # 4. Detect regions
    for name, canonical in sorted(REGIONS.items(), key=lambda x: len(x[0]), reverse=True):
        if name in q_lower:
            result.detected_terms[canonical] = DetectedTerm(
                category="region", value=canonical, column="GRANDPARENTREGIONNAME"
            )
            break

    # 5. Detect divisions
    for name, canonical in sorted(DIVISIONS.items(), key=lambda x: len(x[0]), reverse=True):
        if name in q_lower:
            result.detected_terms[canonical] = DetectedTerm(
                category="division", value=canonical, column="DIVISIONNAME"
            )
            break

    # 6. Detect entities
    for name, canonical in sorted(ENTITIES.items(), key=lambda x: len(x[0]), reverse=True):
        if name in q_lower:
            result.detected_terms[canonical] = DetectedTerm(
                category="entity", value=canonical, column="ENTITYDESCRIPTION"
            )
            break

    # 7a. Detect attrition period terms (longest match first → SQL filter)
    # Also handle common typos via simple normalization
    _q_normalized = re.sub(r"quater\b", "quarter", q_lower)   # quater → quarter
    _q_normalized = re.sub(r"yr\b", "year", _q_normalized)    # yr → year
    _q_normalized = re.sub(r"\bprevious\b", "last", _q_normalized)  # previous → last
    for phrase, sql_filter in sorted(ATTRITION_PERIODS.items(), key=lambda x: len(x[0]), reverse=True):
        if phrase in q_lower or phrase in _q_normalized:
            result.detected_terms[f"PERIOD_{phrase.replace(' ', '_').upper()}"] = DetectedTerm(
                category="attrition_period", value=sql_filter, column="DATE"
            )
            result.detected_period = phrase
            break

    # 7b. Detect generic period patterns (fallback)
    if not result.detected_period:
        for pattern, period_type in PERIOD_PATTERNS:
            match = re.search(pattern, q_lower)
            if match:
                result.detected_period = match.group(0)
                break

    # 8. Detect aggregation modifiers
    for pattern, agg_type in AGGREGATION_PATTERNS:
        match = re.search(pattern, q_lower)
        if match:
            result.detected_aggregation = agg_type
            break

    # 9. Detect numeric values (cost center, employee ID, etc.)
    numeric_match = re.search(r"\b(\d{3,10})\b", question)
    if numeric_match:
        num_val = numeric_match.group(1)
        if "cost center" in q_lower or "costcenter" in q_lower:
            result.detected_terms[f"CC_{num_val}"] = DetectedTerm(
                category="costcenter", value=num_val, column="COSTCENTER"
            )

    return result
