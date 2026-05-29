"""
Intent extraction: detects KPI, terms (station, customer, region, division),
period, and aggregation modifiers from natural language questions.

All term knowledge is loaded from Neo4j at startup — no hardcoded values.
"""

import re
from rapidfuzz import process as fz_process, fuzz
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

# Fuzzy match thresholds — tuned per category to balance recall vs. false positives
FUZZY_KPI_THRESHOLD = 78       # KPI synonym phrases embedded in longer sentences
FUZZY_PERIOD_THRESHOLD = 85    # Period terms (short, need precision)
FUZZY_ENTITY_THRESHOLD = 80    # Customer / region / division names
# Station codes (3-4 chars) are always exact — fuzzy too risky (ATL vs ATS)


def _fuzzy_find(query: str, candidates: list[str], threshold: int) -> str | None:
    """
    Return the best fuzzy match from candidates for query, or None if below threshold.
    Uses partial_ratio for short phrases inside longer sentences (KPI/period detection)
    and token_set_ratio for entity names.
    """
    if not candidates:
        return None
    result = fz_process.extractOne(
        query, candidates,
        scorer=fuzz.partial_ratio,
        score_cutoff=threshold,
    )
    return result[0] if result else None


def _fuzzy_find_entity(query: str, candidates: list[str], threshold: int) -> str | None:
    """Token-set ratio for multi-word entity names (customers, regions, divisions)."""
    if not candidates:
        return None
    result = fz_process.extractOne(
        query, candidates,
        scorer=fuzz.token_set_ratio,
        score_cutoff=threshold,
    )
    return result[0] if result else None


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

    # 1. Detect KPI — collect exact matches (all of them), then fuzzy candidates,
    #    pick winner by (score DESC, phrase_length DESC) so longer phrases beat
    #    short exact matches like 'cost center' when a better typo match exists.
    if KPI_SYNONYMS:
        kpi_phrases = list(KPI_SYNONYMS.keys())
        candidates: list[tuple[str, float]] = []

        # Exact matches get score 100
        for phrase in kpi_phrases:
            if phrase in q_lower:
                candidates.append((phrase, 100.0))

        # Fuzzy matches (may score higher combined with length tie-breaking)
        fuzzy_matches = fz_process.extract(
            q_lower, kpi_phrases,
            scorer=fuzz.partial_ratio,
            score_cutoff=FUZZY_KPI_THRESHOLD,
            limit=10,
        )
        for phrase, score, _ in fuzzy_matches:
            if phrase not in [c[0] for c in candidates]:
                candidates.append((phrase, float(score)))

        if candidates:
            # Sort by (score DESC, phrase_length DESC) — longer phrase wins ties
            best_phrase = sorted(candidates, key=lambda x: (x[1], len(x[0])), reverse=True)[0][0]
            canonical, kpi_id = KPI_SYNONYMS[best_phrase]
            result.detected_kpi = canonical
            result.detected_kpi_id = kpi_id
            logger.debug("kpi_matched", query=q_lower, matched=best_phrase)

    # 2. Detect stations (case-insensitive word match against uppercase codes)
    words = re.findall(r"\b[A-Za-z]{2,4}\b", question)
    for word in words:
        if word.upper() in STATIONS:
            result.detected_terms[word.upper()] = DetectedTerm(
                category="station", value=word.upper(), column="STATIONCODE"
            )
            break

    # 3. Detect customers — exact first, then fuzzy fallback
    detected_station_values = {t.value for t in result.detected_terms.values() if t.category == "station"}
    matched_customer = False
    for name, canonical in sorted(CUSTOMERS.items(), key=lambda x: len(x[0]), reverse=True):
        if name in q_lower:
            if any(st in name.upper() for st in detected_station_values):
                continue
            if re.search(rf"\b{re.escape(name)}\b", q_lower):
                result.detected_terms[canonical] = DetectedTerm(
                    category="customer", value=canonical, column="CUSTOMERNAME"
                )
                matched_customer = True
                break
    if not matched_customer:
        best = _fuzzy_find_entity(q_lower, list(CUSTOMERS.keys()), FUZZY_ENTITY_THRESHOLD)
        if best and not any(st in best.upper() for st in detected_station_values):
            canonical = CUSTOMERS[best]
            result.detected_terms[canonical] = DetectedTerm(
                category="customer", value=canonical, column="CUSTOMERNAME"
            )
            logger.debug("customer_fuzzy_matched", query=q_lower, matched=best)

    # 4. Detect regions — exact then fuzzy
    matched_region = False
    for name, canonical in sorted(REGIONS.items(), key=lambda x: len(x[0]), reverse=True):
        if name in q_lower:
            result.detected_terms[canonical] = DetectedTerm(
                category="region", value=canonical, column="GRANDPARENTREGIONNAME"
            )
            matched_region = True
            break
    if not matched_region:
        best = _fuzzy_find_entity(q_lower, list(REGIONS.keys()), FUZZY_ENTITY_THRESHOLD)
        if best:
            result.detected_terms[REGIONS[best]] = DetectedTerm(
                category="region", value=REGIONS[best], column="GRANDPARENTREGIONNAME"
            )
            logger.debug("region_fuzzy_matched", query=q_lower, matched=best)

    # 5. Detect divisions — exact then fuzzy
    matched_division = False
    for name, canonical in sorted(DIVISIONS.items(), key=lambda x: len(x[0]), reverse=True):
        if name in q_lower:
            result.detected_terms[canonical] = DetectedTerm(
                category="division", value=canonical, column="DIVISIONNAME"
            )
            matched_division = True
            break
    if not matched_division:
        best = _fuzzy_find_entity(q_lower, list(DIVISIONS.keys()), FUZZY_ENTITY_THRESHOLD)
        if best:
            result.detected_terms[DIVISIONS[best]] = DetectedTerm(
                category="division", value=DIVISIONS[best], column="DIVISIONNAME"
            )
            logger.debug("division_fuzzy_matched", query=q_lower, matched=best)

    # 6. Detect entities — exact then fuzzy
    matched_entity = False
    for name, canonical in sorted(ENTITIES.items(), key=lambda x: len(x[0]), reverse=True):
        if name in q_lower:
            result.detected_terms[canonical] = DetectedTerm(
                category="entity", value=canonical, column="ENTITYDESCRIPTION"
            )
            matched_entity = True
            break
    if not matched_entity:
        best = _fuzzy_find_entity(q_lower, list(ENTITIES.keys()), FUZZY_ENTITY_THRESHOLD)
        if best:
            result.detected_terms[ENTITIES[best]] = DetectedTerm(
                category="entity", value=ENTITIES[best], column="ENTITYDESCRIPTION"
            )
            logger.debug("entity_fuzzy_matched", query=q_lower, matched=best)

    # 7a. Detect attrition period terms — exact first, then fuzzy fallback
    matched_period = False
    period_phrases = list(ATTRITION_PERIODS.keys())
    for phrase, sql_filter in sorted(ATTRITION_PERIODS.items(), key=lambda x: len(x[0]), reverse=True):
        if phrase in q_lower:
            result.detected_terms[f"PERIOD_{phrase.replace(' ', '_').upper()}"] = DetectedTerm(
                category="attrition_period", value=sql_filter, column="DATE"
            )
            result.detected_period = phrase
            matched_period = True
            break
    if not matched_period and period_phrases:
        best = _fuzzy_find(q_lower, period_phrases, FUZZY_PERIOD_THRESHOLD)
        if best:
            sql_filter = ATTRITION_PERIODS[best]
            result.detected_terms[f"PERIOD_{best.replace(' ', '_').upper()}"] = DetectedTerm(
                category="attrition_period", value=sql_filter, column="DATE"
            )
            result.detected_period = best
            logger.debug("period_fuzzy_matched", query=q_lower, matched=best)

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
