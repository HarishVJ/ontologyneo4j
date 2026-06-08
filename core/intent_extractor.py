"""
Intent extraction: detects KPI, terms, period, and aggregation modifiers from natural language questions.

All term knowledge is loaded from Neo4j at startup — no hardcoded values.
Categories, match strategies, and thresholds are fully data-driven via TermCategory nodes.
"""

import re
from rapidfuzz import process as fz_process, fuzz
from core.models import ExtractionResult, DetectedTerm, ThresholdFilter
from core.date_parser import parse_period, parse_time_grouping
from core.neo4j_client import execute_query
from config.logging_config import get_logger

logger = get_logger(__name__)

# ─── Global category cache — populated from Neo4j TermCategory + Term nodes ──
# TERM_CATEGORIES[category_name] = {
#   "column": str|None, "value_kind": str, "match_type": str,
#   "threshold": int, "priority": int, "extractable": bool,
#   "pattern": str|None, "conflicts_with": list[str],
#   "terms": dict   # populated from Term nodes
# }
TERM_CATEGORIES: dict[str, dict] = {}

_terms_loaded = False


# ─── Fuzzy helpers (reused by strategy dispatcher) ──────────────────────────
def _fuzzy_find(query: str, candidates: list[str], threshold: int) -> str | None:
    """partial_ratio for short phrases inside longer sentences."""
    if not candidates:
        return None
    result = fz_process.extractOne(
        query, candidates, scorer=fuzz.partial_ratio, score_cutoff=threshold,
    )
    return result[0] if result else None


def _fuzzy_find_entity(query: str, candidates: list[str], threshold: int) -> str | None:
    """token_set_ratio for multi-word entity names."""
    if not candidates:
        return None
    result = fz_process.extractOne(
        query, candidates, scorer=fuzz.token_set_ratio, score_cutoff=threshold,
    )
    return result[0] if result else None


# ─── Period & aggregation patterns (engine-level, not ontology terms) ──────
PERIOD_PATTERNS = [
    (r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s*'?\d{2,4}\b", "month_year"),
    (r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s*'?\d{2,4}\b", "month_year"),
    (r"\bq[1-4]\s*'?\d{2,4}\b", "quarter"),
    (r"\blast\s+(month|quarter|year|6\s*months|3\s*months)\b", "relative"),
    (r"\b(20\d{2})\b", "year"),
    (r"\b(ytd|year\s*to\s*date)\b", "ytd"),
    (r"\bcurrent\s+month\b", "current_month"),
]

AGGREGATION_PATTERNS = [
    (r"\btop\s+(\d+)\b", "top_n"),
    (r"\bhighest\b", "max"),
    (r"\blowest\b", "min"),
    (r"\baverage\b", "avg"),
    (r"\btotal\b", "sum"),
]

# ─── Metric threshold patterns ───────────────────────────────────────────
THRESHOLD_PATTERNS = [
    (r"\b(more than|greater than|over|above|exceeding|exceeds?)\s+(\d+(?:\.\d+)?)\s*(%|percent|hours|employees?|people|staff)?\b", ">"),
    (r"\b(less than|under|below|fewer than)\s+(\d+(?:\.\d+)?)\s*(%|percent|hours|employees?|people|staff)?\b", "<"),
    (r"\b(at least|no less than)\s+(\d+(?:\.\d+)?)\s*(%|percent|hours|employees?|people|staff)?\b", ">="),
    (r"\b(at most|no more than)\s+(\d+(?:\.\d+)?)\s*(%|percent|hours|employees?|people|staff)?\b", "<="),
    (r"\b(\d+(?:\.\d+)?)\s*(%|percent)\s*(or more|or higher|or above|plus)\b", ">="),
    (r"\b(\d+(?:\.\d+)?)\s*(%|percent)\s*(or less|or lower|or under)\b", "<="),
]

_UNIT_TO_METRIC = {
    "%": None,
    "percent": None,
    "hours": "TOTAL_HOURS",
    "employee": "EMPLOYEE_COUNT",
    "employees": "EMPLOYEE_COUNT",
    "people": "EMPLOYEE_COUNT",
    "staff": "EMPLOYEE_COUNT",
}


# ─── Loaders ──────────────────────────────────────────────────────────────────
def load_terms_from_neo4j() -> None:
    """Load TermCategory metadata and all Term values from Neo4j."""
    global TERM_CATEGORIES, _terms_loaded

    try:
        # 1. Load category metadata
        cat_records = execute_query("MATCH (tc:TermCategory) RETURN tc {.*} AS tc")
        for r in cat_records:
            tc = r["tc"]
            name = tc["name"]
            TERM_CATEGORIES[name] = {
                "name": name,
                "column": tc.get("column"),
                "value_kind": tc.get("value_kind", ""),
                "match_type": tc.get("match_type", ""),
                "threshold": tc.get("threshold", -1),
                "priority": tc.get("priority", -1),
                "extractable": tc.get("extractable", True),
                "groupable": tc.get("groupable", False),
                "pattern": tc.get("pattern") or None,
                "conflicts_with": tc.get("conflicts_with", []),
                "terms": {},
                "canonical_map": {},
                "canonical_keys": set(),
            }

        # 2. Load terms into their categories
        term_records = execute_query(
            "MATCH (t:Term) RETURN t.code AS code, t.canonical AS canonical, "
            "t.category AS category, t.column AS column, t.kpi_id AS kpi_id, t.context AS context"
        )
        for r in term_records:
            cat = r["category"]
            if cat not in TERM_CATEGORIES:
                continue
            code = r["code"]
            canonical = r["canonical"] or code
            context = r.get("context", "")
            kpi_id = r.get("kpi_id", "")
            cfg = TERM_CATEGORIES[cat]

            if cat == "kpi_synonyms":
                cfg["terms"][code.lower()] = (canonical, kpi_id)
            elif cfg["value_kind"] == "sql_expr":
                sql_filter = context or ""
                if sql_filter:
                    cfg["terms"][code.lower()] = sql_filter
            elif cfg["match_type"] == "exact":
                cfg["terms"][code.upper()] = canonical
                # Index canonical name for entity-by-name matching
                if canonical and canonical != code:
                    c_key = canonical.lower()
                    cfg["canonical_map"][c_key] = code
                    cfg["canonical_keys"].add(c_key)
                    cfg["terms"][c_key] = code
            else:
                cfg["terms"][code.lower()] = canonical
                if canonical and canonical != code:
                    c_key = canonical.lower()
                    cfg["canonical_map"][c_key] = code
                    cfg["canonical_keys"].add(c_key)
                    cfg["terms"][c_key] = code

        _terms_loaded = True
        logger.info(
            "terms_loaded_from_neo4j",
            categories=len(TERM_CATEGORIES),
            total_terms=sum(len(c["terms"]) for c in TERM_CATEGORIES.values()),
        )
    except Exception as e:
        logger.error("term_loading_failed", error=str(e))
        _terms_loaded = False


# ─── Strategy dispatchers (one per match_type) ─────────────────────────────
def _match_exact(cfg: dict, question: str, q_lower: str) -> list[DetectedTerm]:
    """Exact word match — station-style (3-4 char codes) or canonical name.
    Collects ALL unique matches so multi-value queries (e.g. 'MSP and ATL') work.
    """
    found: list[DetectedTerm] = []
    seen: set[str] = set()
    words = re.findall(r"\b[A-Za-z]{2,}\b", question)
    for word in words:
        word_upper = word.upper()
        word_lower = word.lower()
        if word_upper in cfg["terms"] and word_upper not in seen:
            seen.add(word_upper)
            found.append(DetectedTerm(
                category=cfg["name"],
                value=word_upper,
                column=cfg["column"],
                value_kind=cfg["value_kind"],
            ))
        # Entity-by-name: canonical name exact match
        elif word_lower in cfg.get("canonical_keys", set()):
            code = cfg["canonical_map"].get(word_lower, word_upper)
            code_upper = code.upper()
            if code_upper not in seen:
                seen.add(code_upper)
                found.append(DetectedTerm(
                    category=cfg["name"],
                    value=code_upper,
                    column=cfg["column"],
                    value_kind=cfg["value_kind"],
                ))
    return found


def _match_fuzzy_token(cfg: dict, question: str, q_lower: str) -> list[DetectedTerm]:
    """Token-set fuzzy — customer / region / division / entity style."""
    found: list[DetectedTerm] = []
    terms = cfg["terms"]
    threshold = cfg["threshold"] if cfg["threshold"] > 0 else 80

    # Exact first (longest match wins)
    matched = False
    use_code = cfg["value_kind"] == "code"
    ckeys = cfg.get("canonical_keys", set())
    cmap = cfg.get("canonical_map", {})
    for name, canonical in sorted(terms.items(), key=lambda x: len(x[0]), reverse=True):
        if name in q_lower:
            if re.search(rf"\b{re.escape(name)}\b", q_lower):
                if use_code and name in ckeys:
                    val = cmap.get(name, name.upper()).upper()
                else:
                    val = name.upper() if use_code else canonical
                found.append(DetectedTerm(
                    category=cfg["name"],
                    value=val,
                    column=cfg["column"],
                    value_kind=cfg["value_kind"],
                ))
                matched = True
                break

    # Fuzzy fallback
    if not matched:
        best = _fuzzy_find_entity(q_lower, list(terms.keys()), threshold)
        if best:
            if use_code and best in ckeys:
                val = cmap.get(best, best.upper()).upper()
            else:
                val = best.upper() if use_code else terms[best]
            found.append(DetectedTerm(
                category=cfg["name"],
                value=val,
                column=cfg["column"],
                value_kind=cfg["value_kind"],
            ))
    return found


def _match_fuzzy_partial(cfg: dict, question: str, q_lower: str) -> list[DetectedTerm]:
    """Partial fuzzy — period / phrase style."""
    found: list[DetectedTerm] = []
    terms = cfg["terms"]
    threshold = cfg["threshold"] if cfg["threshold"] > 0 else 85

    matched = False
    use_code = cfg["value_kind"] == "code"
    ckeys = cfg.get("canonical_keys", set())
    cmap = cfg.get("canonical_map", {})
    for phrase, value in sorted(terms.items(), key=lambda x: len(x[0]), reverse=True):
        if phrase in q_lower:
            if use_code and phrase in ckeys:
                val = cmap.get(phrase, phrase.upper()).upper()
            else:
                val = phrase.upper() if use_code else value
            found.append(DetectedTerm(
                category=cfg["name"],
                value=val,
                column=cfg["column"],
                value_kind=cfg["value_kind"],
            ))
            matched = True
            break

    if not matched and terms:
        best = _fuzzy_find(q_lower, list(terms.keys()), threshold)
        if best:
            if use_code and best in ckeys:
                val = cmap.get(best, best.upper()).upper()
            else:
                val = best.upper() if use_code else terms[best]
            found.append(DetectedTerm(
                category=cfg["name"],
                value=val,
                column=cfg["column"],
                value_kind=cfg["value_kind"],
            ))
    return found


def _match_numeric_regex(cfg: dict, question: str, q_lower: str) -> list[DetectedTerm]:
    """Regex-based numeric extraction — cost centre, employee ID, etc."""
    found: list[DetectedTerm] = []
    pattern = cfg.get("pattern")
    if not pattern:
        return found

    # Special-case gating: cost centre needs the phrase "cost center"
    if cfg["name"] == "costcenter":
        if "cost center" not in q_lower and "costcenter" not in q_lower:
            return found

    match = re.search(pattern, question)
    if match:
        found.append(DetectedTerm(
            category=cfg["name"],
            value=match.group(1),
            column=cfg["column"],
            value_kind=cfg["value_kind"],
        ))
    return found


def _detect_grouping(q_lower: str) -> list[str]:
    """Scan question for group-by patterns and return list of column names."""
    group_columns: list[str] = []

    # Patterns: "by X", "by X and Y", "distribution by X", "X breakdown", "grouped by X"
    patterns = [
        r"\bdistribution\s+by\s+(.+?)(?:\?|$|\band\b|\bfor\b|\bin\b|\bat\b)",
        r"\bbreakdown\s+by\s+(.+?)(?:\?|$|\band\b|\bfor\b|\bin\b|\bat\b)",
        r"\bgrouped?\s+by\s+(.+?)(?:\?|$|\band\b|\bfor\b|\bin\b|\bat\b)",
        r"\bby\s+(.+?)(?:\?|$|\band\b|\bfor\b|\bin\b|\bat\b)",
    ]

    # Try each pattern to find dimension phrase(s)
    dim_phrases: list[str] = []
    for pat in patterns:
        match = re.search(pat, q_lower)
        if match:
            raw = match.group(1)
            # Split on 'and' or commas for multi-dim
            parts = re.split(r",?\s+and\s+|,\s*", raw)
            for p in parts:
                p = p.strip()
                if p and len(p) > 1:
                    dim_phrases.append(p)
            break  # use first match

    if not dim_phrases:
        return group_columns

    # Resolve each dimension phrase against groupable categories
    groupable_cats = {
        name: cfg for name, cfg in TERM_CATEGORIES.items()
        if cfg.get("groupable") and cfg.get("terms")
    }

    for phrase in dim_phrases:
        matched = False
        for cat_name, cfg in groupable_cats.items():
            # Try exact match against canonical or code
            for code, canonical in cfg["terms"].items():
                # The canonical is what the user might say; e.g. "atlanta" maps to ATL
                # But for grouping, we care about the column, not the value.
                # We need to check if the phrase describes the *category* itself
                pass
            # Instead of matching values, match category names / aliases
            cat_aliases = {
                cat_name.replace("_", " "),
                cat_name.replace("_", ""),
                cfg.get("column", "").lower(),
            }
            # Add canonical-to-alias mapping for common business terms
            biz_aliases: dict[str, list[str]] = {
                "stations": ["station", "airport", "hub", "site"],
                "customers": ["customer", "airline", "client"],
                "regions": ["region", "grandparentregion"],
                "divisions": ["division", "line of business"],
                "entities": ["entity", "legal entity", "company"],
                "costcenter": ["cost center", "costcenter", "cc"],
                "sub_regions": ["sub region", "subregion"],
                "service_types": ["service type", "line of service", "los"],
                "departments": ["department", "dept"],
                "cities": ["city", "town"],
                "states": ["state", "province"],
                "postal_codes": ["postal code", "zip code", "zip"],
            }
            aliases = set(biz_aliases.get(cat_name, []))
            if phrase in aliases or phrase + "s" in aliases:
                col = cfg.get("column")
                if col and col not in group_columns:
                    group_columns.append(col)
                matched = True
                break

            # Also try fuzzy matching the phrase against aliases
            for alias in aliases:
                if alias and len(alias) >= 3:
                    # Check if the phrase contains the alias or vice versa
                    if alias in phrase or phrase in alias:
                        col = cfg.get("column")
                        if col and col not in group_columns:
                            group_columns.append(col)
                        matched = True
                        break
            if matched:
                break

        # If no category matched, try matching against known term values
        if not matched:
            for cat_name, cfg in groupable_cats.items():
                for code, canonical in cfg["terms"].items():
                    # If phrase equals a canonical value, that means "group by that specific value"
                    # which doesn't make sense. Instead, we want "group by the dimension that has that value"
                    # So we skip value-level matching and only do category-level.
                    pass

    return group_columns


def _detect_thresholds(q_lower: str, detected_kpi: str | None) -> list[ThresholdFilter]:
    """Detect metric threshold patterns (e.g. 'more than 10%', 'exceeding 40 hours').
    Maps trailing unit keywords to likely metric columns via heuristic."""
    thresholds = []
    for pattern, operator in THRESHOLD_PATTERNS:
        match = re.search(pattern, q_lower)
        if match:
            groups = match.groups()
            value = None
            unit = None
            for g in groups:
                if g is None:
                    continue
                g_stripped = g.strip()
                if re.match(r"^\d+(?:\.\d+)?$", g_stripped):
                    value = g_stripped
                elif g_stripped in _UNIT_TO_METRIC:
                    unit = g_stripped
            if not value:
                continue

            metric = _UNIT_TO_METRIC.get(unit) if unit else None

            if not metric:
                if any(w in q_lower for w in ["rate", "percentage", "pct", "%", "percent"]):
                    metric = "ATTRITION_RATE_PCT"
                elif any(w in q_lower for w in ["hour", "overtime", "ot ", "time "]):
                    metric = "TOTAL_HOURS"
                elif any(w in q_lower for w in ["employee", "headcount", "people", "staff"]):
                    metric = "EMPLOYEE_COUNT"
                elif any(w in q_lower for w in ["termination", "left", "quit"]):
                    metric = "TERMINATION_COUNT"

            if not metric:
                metric = "VALUE"

            sql_expr = f"{metric} {operator} {value}"
            thresholds.append(ThresholdFilter(metric=metric, operator=operator, value=value, sql_expr=sql_expr))
            break

    return thresholds


# ─── Main extraction entry-point ────────────────────────────────────────────
def extract(question: str) -> ExtractionResult:
    """Extract intent, terms, period, and modifiers from a natural language question."""
    if not _terms_loaded:
        load_terms_from_neo4j()

    q_lower = question.lower()
    result = ExtractionResult(original_question=question)

    # ── 1. Detect KPI (kpi_synonyms are handled specially) ──────────────────
    kpi_cfg = TERM_CATEGORIES.get("kpi_synonyms")
    if kpi_cfg and kpi_cfg["terms"]:
        kpi_terms = kpi_cfg["terms"]  # lowercase phrase -> (canonical, kpi_id)
        kpi_phrases = list(kpi_terms.keys())
        candidates: list[tuple[str, float]] = []

        # Exact matches get score 100
        for phrase in kpi_phrases:
            if phrase in q_lower:
                candidates.append((phrase, 100.0))

        # Fuzzy matches
        threshold = kpi_cfg["threshold"] if kpi_cfg["threshold"] > 0 else 78
        fuzzy_matches = fz_process.extract(
            q_lower, kpi_phrases, scorer=fuzz.partial_ratio,
            score_cutoff=threshold, limit=10,
        )
        for phrase, score, _ in fuzzy_matches:
            if phrase not in [c[0] for c in candidates]:
                candidates.append((phrase, float(score)))

        if candidates:
            best_phrase = sorted(candidates, key=lambda x: (x[1], len(x[0])), reverse=True)[0][0]
            canonical, kpi_id = kpi_terms[best_phrase]
            result.detected_kpi = canonical
            result.detected_kpi_id = kpi_id
            logger.debug("kpi_matched", query=q_lower, matched=best_phrase)

    # ── 2. Detect extractable categories in priority order ──────────────────
    extractable = [
        (name, cfg) for name, cfg in TERM_CATEGORIES.items()
        if cfg["extractable"] and name != "kpi_synonyms"
    ]
    extractable.sort(key=lambda x: x[1]["priority"], reverse=True)

    for cat_name, cfg in extractable:
        if not cfg["terms"] and cfg["match_type"] != "numeric_regex":
            continue

        match_type = cfg["match_type"]
        if match_type == "exact":
            found = _match_exact(cfg, question, q_lower)
        elif match_type == "fuzzy_token":
            found = _match_fuzzy_token(cfg, question, q_lower)
        elif match_type == "fuzzy_partial":
            found = _match_fuzzy_partial(cfg, question, q_lower)
        elif match_type == "numeric_regex":
            found = _match_numeric_regex(cfg, question, q_lower)
        else:
            continue

        for term in found:
            # For attrition_period, try the generic date parser first
            if term.category == "attrition_period":
                # Find the original phrase that matched
                matched_phrase = None
                for ph, val in cfg["terms"].items():
                    if val == term.value:
                        matched_phrase = ph
                        break
                if matched_phrase:
                    parsed_sql = parse_period(matched_phrase)
                    if parsed_sql:
                        term.value = parsed_sql
                        term.column = None  # bound later in context_builder
                    result.detected_period = matched_phrase

            key = f"{term.category}_{term.value.replace(' ', '_').upper()}"
            result.detected_terms[key] = term

    # ── 3. Apply conflicts_with exclusions (content-aware) ──────────────────
    detected_station_values = {t.value for t in result.detected_terms.values() if t.category == "stations"}
    if detected_station_values and "customers" in TERM_CATEGORIES:
        # If a customer term contains a station code, remove it (preserves old overlap rule)
        to_remove = []
        for key, term in result.detected_terms.items():
            if term.category == "customers" and any(st in term.value.upper() for st in detected_station_values):
                to_remove.append(key)
        for key in to_remove:
            del result.detected_terms[key]
            logger.debug("conflict_excluded", category="customers", reason="station_overlap")

    # ── 4. Generic period patterns (fallback) ────────────────────────────────
    if not result.detected_period:
        for pattern, period_type in PERIOD_PATTERNS:
            match = re.search(pattern, q_lower)
            if match:
                period_phrase = match.group(0)
                period_sql = parse_period(period_phrase)
                if period_sql:
                    key = f"PERIOD_{period_phrase.replace(' ', '_').upper()}"
                    result.detected_terms[key] = DetectedTerm(
                        category="attrition_period",
                        value=period_sql,
                        column=None,
                        value_kind="sql_expr",
                    )
                    result.detected_period = period_phrase
                break

    # ── 5. Aggregation modifiers ────────────────────────────────────────────
    for pattern, agg_type in AGGREGATION_PATTERNS:
        match = re.search(pattern, q_lower)
        if match:
            result.detected_aggregation = agg_type
            if agg_type == "top_n":
                try:
                    result.detected_limit = int(match.group(1))
                except (ValueError, IndexError):
                    result.detected_limit = 10
            break

    # ── 6. Group-by detection ───────────────────────────────────────────────
    result.detected_grouping = _detect_grouping(q_lower)

    # ── 7. Time-grouping detection (monthly, quarterly, yearly) ───────────────
    time_group = parse_time_grouping(q_lower)
    if time_group and time_group not in result.detected_grouping:
        result.detected_grouping.append(time_group)

    # ── 8. Metric threshold detection ────────────────────────────────────────
    result.detected_thresholds = _detect_thresholds(q_lower, result.detected_kpi)

    logger.info(
        "extraction_complete",
        kpi=result.detected_kpi,
        terms=list(result.detected_terms.keys()),
        period=result.detected_period,
        grouping=result.detected_grouping,
        aggregation=result.detected_aggregation,
        thresholds=[t.sql_expr for t in result.detected_thresholds],
    )
    return result
