"""
Unknown entity detector.

Identifies candidate business-entity tokens in a user question that were NOT
resolved by the intent extractor, then checks whether they look like known
dimension values.  If an entity-like token cannot be matched, the pipeline
returns a clarification request instead of generating SQL.
"""

import re
from rapidfuzz import process as fz_process, fuzz

from core.models import (
    ClarificationRequest,
    ExtractionResult,
    KPIRecipe,
    UnknownEntityCandidate,
)
from core.intent_extractor import TERM_CATEGORIES
from config.logging_config import get_logger

logger = get_logger(__name__)

# Words that are never treated as unknown entities
_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "dare",
    "ought", "used", "what", "which", "who", "whom", "whose", "where",
    "when", "why", "how", "that", "this", "these", "those", "i", "you",
    "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "her", "its", "our", "their", "mine", "yours",
    "hers", "ours", "theirs", "and", "or", "but", "so", "yet", "for",
    "nor", "although", "though", "because", "since", "unless", "until",
    "while", "whereas", "if", "then", "else", "whether", "either", "neither",
    "both", "all", "any", "each", "every", "some", "many", "much", "more",
    "most", "few", "little", "less", "least", "several", "various", "of",
    "to", "in", "on", "at", "by", "with", "from", "into", "onto", "upon",
    "about", "above", "across", "after", "against", "along", "among",
    "around", "before", "behind", "below", "beneath", "beside", "between",
    "beyond", "inside", "outside", "under", "within", "without", "through",
    "throughout", "toward", "towards", "up", "down", "off", "over", "out",
    "away", "back", "forward", "here", "there", "now", "today", "tomorrow",
    "yesterday", "show", "give", "get", "list", "find", "tell", "rate",
    "number", "count", "total", "summary", "detail", "breakdown", "data",
    "result", "results", "information", "value", "values", "percent",
    "percentage", "rate", "avg", "average", "sum", "min", "max", "top",
    "bottom", "highest", "lowest", "more", "than", "quarter", "month",
    "year", "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december", "jan", "feb",
    "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    "q1", "q2", "q3", "q4", "ytd", "current", "last", "next", "previous",
    "me", "employee", "employees", "headcount", "people", "staff",
    "workforce", "left", "terminated", "attrition", "turnover", "termination",
    "contract", "contracts", "station", "stations", "airport", "airports",
    "hub", "hubs", "customer", "customers", "client", "clients", "region",
    "regions", "division", "divisions", "entity", "entities", "cost",
    "center", "costcenter", "costcenters", "department", "departments",
    "service", "services", "type", "types", "status", "active", "inactive",
    "hour", "hours", "overtime", "ot", "regular", "holiday", "pto", "vacation",
    "pay", "code", "codes", "worked", "during", "period", "time", "date",
    "dates", "from", "between", "starting", "ending", "start", "end",
    "day", "days", "week", "weeks", "ago", "daily", "weekly", "monthly",
    "yearly", "quarterly", "annual", "annually", "fiscal", "fy", "ytd",
    "mtd", "qtd", "wtd", "trailing", "rolling", "past", "recent",
}

# Prepositions that often precede a business entity
_ENTITY_PREPOSITIONS = ["for", "at", "in", "by"]


def detect_unknown_entities(
    question: str,
    extraction: ExtractionResult,
    recipe: KPIRecipe,
) -> UnknownEntityCandidate | None:
    """
    Return the first unknown entity candidate, or None if everything is resolved.
    """
    q_lower = question.lower()

    # 1. Determine which categories this KPI supports natively
    supported_native = _native_categories(recipe)
    if not supported_native:
        return None

    # 2. Build the set of tokens already consumed by the extractor
    consumed = _consumed_tokens(extraction)

    # 3. Extract candidate entity-like tokens
    candidates = _extract_candidates(q_lower, consumed)
    if not candidates:
        return None

    # 4. For each candidate, check whether it is known in any supported category
    for candidate in candidates:
        match = _find_in_categories(candidate, supported_native)
        if match is None:
            # Unknown entity — generate suggestions via fuzzy match
            suggestions = _get_suggestions(candidate, supported_native)
            guessed = list(supported_native.keys())
            reason = (
                f'"{candidate}" looks like a business entity '
                f"but was not found in the ontology for {recipe.name}."
            )
            return UnknownEntityCandidate(
                raw_text=candidate,
                guessed_categories=guessed,
                suggestions=suggestions,
                reason=reason,
            )

    return None


def _native_categories(recipe: KPIRecipe) -> dict[str, dict]:
    """Return TERM_CATEGORIES entries that this KPI supports natively."""
    native: dict[str, dict] = {}
    for cat_name, rule in recipe.dimension_rules.items():
        if isinstance(rule, dict) and rule.get("support_type") == "native":
            cfg = TERM_CATEGORIES.get(cat_name)
            if cfg:
                native[cat_name] = cfg
    return native


def _consumed_tokens(extraction: ExtractionResult) -> set[str]:
    """Tokens/phrases already resolved by the extractor."""
    consumed: set[str] = set()

    def _add(value: str) -> None:
        v = value.strip().lower()
        if not v:
            return
        consumed.add(v)
        # Also add each word so multi-word phrases don't leak as candidates
        for word in re.findall(r"[a-z0-9]+", v):
            consumed.add(word)

    # Detected terms
    for term in extraction.detected_terms.values():
        _add(term.value)
    # Period (e.g. "last 90 days", "ytd")
    if extraction.detected_period:
        _add(extraction.detected_period)
    # Grouping
    for g in extraction.detected_grouping:
        _add(g)
    return consumed


def _extract_candidates(q_lower: str, consumed: set[str]) -> list[str]:
    """
    Extract tokens that look like unresolved business entities.

    Strategy:
      - Find all words after entity prepositions (for/at/in/by)
      - Include 3–5 char uppercase-like tokens anywhere
      - Exclude stop words and already-consumed tokens
    """
    candidates: list[str] = []

    # A. Tokens after prepositions  (e.g. "for BOH", "at MSP", "for customer Delta")
    #    Capture up to 3 words, then drop stop words, consumed tokens, and bare
    #    numbers so trailing period/qualifier words (e.g. "MSP ytd", "the last 90")
    #    don't get mistaken for an entity.
    for prep in _ENTITY_PREPOSITIONS:
        pattern = rf"\b{prep}\s+([a-z0-9]+(?:\s+[a-z0-9]+){{0,2}})"
        for match in re.finditer(pattern, q_lower):
            words = [
                w
                for w in match.group(1).split()
                if w not in _STOP_WORDS
                and w not in consumed
                and not w.isdigit()
            ]
            if words:
                candidates.append(" ".join(words))

    # B. Standalone 3–5 char tokens that look like codes (all-alpha or alphanumeric)
    for match in re.finditer(r"\b[a-z]{3,5}\b", q_lower):
        token = match.group(0)
        if token not in _STOP_WORDS and token not in consumed:
            candidates.append(token)

    # C. Quoted values  (e.g. "BOH" or 'Acme Corp')
    for match in re.finditer(r'["\']([^"\']+)["\']', q_lower):
        token = match.group(1).strip().lower()
        if token and token not in consumed:
            candidates.append(token)

    # D. Numeric tokens that look like cost-center codes
    for match in re.finditer(r"\b\d{3,6}\b", q_lower):
        token = match.group(0)
        if token not in consumed:
            candidates.append(token)

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def _find_in_categories(candidate: str, supported: dict[str, dict]) -> str | None:
    """
    Check whether `candidate` is a known term in any supported category.
    Returns the matching category name, or None if not found.
    """
    c_lower = candidate.lower()
    c_upper = candidate.upper()

    for cat_name, cfg in supported.items():
        terms = cfg.get("terms", {})
        # Exact match on code (uppercase keys for station-style)
        if c_upper in terms:
            return cat_name
        # Exact match on canonical name (lowercase keys)
        if c_lower in terms:
            return cat_name
        # Check canonical_map
        canonical_map = cfg.get("canonical_map", {})
        if c_lower in canonical_map:
            return cat_name
        canonical_keys = cfg.get("canonical_keys", set())
        if c_lower in canonical_keys:
            return cat_name

    return None


def _get_suggestions(candidate: str, supported: dict[str, dict]) -> list[str]:
    """Return up to 3 fuzzy-matched known values as suggestions."""
    all_known: list[str] = []
    for cfg in supported.values():
        terms = cfg.get("terms", {})
        # Gather both codes and canonicals
        for k, v in terms.items():
            if len(k) <= 6:
                all_known.append(k.upper())
            if v and isinstance(v, str):
                all_known.append(v)

    if not all_known:
        return []

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for v in all_known:
        upper = v.upper()
        if upper not in seen:
            seen.add(upper)
            deduped.append(v)

    results = fz_process.extract(
        candidate.upper(),
        deduped,
        scorer=fuzz.ratio,
        limit=3,
    )
    return [r[0] for r in results if r[1] >= 50]


def to_clarification(candidate: UnknownEntityCandidate) -> ClarificationRequest:
    """Convert an UnknownEntityCandidate into a ClarificationRequest."""
    options = candidate.suggestions[:3]
    if not options:
        question = (
            f'I could not find "{candidate.raw_text}" in the approved dictionary. '
            f"Please provide a valid {', '.join(candidate.guessed_categories)}."
        )
    else:
        question = (
            f'I could not find "{candidate.raw_text}". '
            f'Did you mean: {", ".join(options)}?'
        )

    return ClarificationRequest(
        required_field="unknown_entity",
        question=question,
        options=options,
        reason=candidate.reason,
        raw_value=candidate.raw_text,
        guessed_categories=candidate.guessed_categories,
    )
