from core.models import DetectedTerm, ExtractionResult, KPIRecipe, UnknownEntityCandidate
from core import unknown_entity_detector
from core.unknown_entity_detector import (
    detect_unknown_entities,
    to_clarification,
    _extract_candidates,
    _find_in_categories,
)

# TERM_CATEGORIES is populated from Neo4j at runtime; in tests it is empty, so
# inject a stations category (ATL/MSP/BOS known, BOH unknown) to exercise detection.
_STATIONS_CATEGORY = {
    "stations": {
        "column": "STATIONCODE",
        "terms": {"ATL": "Atlanta", "MSP": "Minneapolis", "BOS": "Boston"},
    }
}


def test_no_unknown_when_all_resolved():
    """ATL is a known station — no unknown entity should be flagged."""
    extraction = ExtractionResult(
        original_question="What is attrition for ATL?",
        detected_kpi="Attrition Rate",
        detected_terms={
            "stations_ATL": DetectedTerm(
                category="stations", value="ATL", column="STATIONCODE", value_kind="code"
            )
        },
    )
    recipe = KPIRecipe(
        id="kpi_attrition",
        name="Attrition Rate",
        description="",
        complexity="simple",
        formula="",
        dimension_rules={
            "stations": {
                "column": "STATIONCODE",
                "filterable": True,
                "groupable": True,
                "support_type": "native",
                "required": False,
            }
        },
    )

    result = detect_unknown_entities("What is attrition for ATL?", extraction, recipe)
    assert result is None


def test_unknown_station_code_detected(monkeypatch):
    """BOH is not a known station — should be flagged as unknown."""
    monkeypatch.setattr(unknown_entity_detector, "TERM_CATEGORIES", _STATIONS_CATEGORY)
    extraction = ExtractionResult(
        original_question="What is attrition for BOH?",
        detected_kpi="Attrition Rate",
        detected_terms={},
    )
    recipe = KPIRecipe(
        id="kpi_attrition",
        name="Attrition Rate",
        description="",
        complexity="simple",
        formula="",
        dimension_rules={
            "stations": {
                "column": "STATIONCODE",
                "filterable": True,
                "groupable": True,
                "support_type": "native",
                "required": False,
            }
        },
    )

    result = detect_unknown_entities("What is attrition for BOH?", extraction, recipe)

    assert result is not None
    assert result.raw_text == "boh"
    assert "stations" in result.guessed_categories


def test_unknown_produces_clarification():
    """Unknown entity should convert to a ClarificationRequest."""
    candidate = UnknownEntityCandidate(
        raw_text="BOH",
        guessed_categories=["stations"],
        suggestions=["BOS", "BWI"],
        reason="Not found",
    )

    clarification = to_clarification(candidate)

    assert clarification.required_field == "unknown_entity"
    assert "BOH" in clarification.question
    assert clarification.options == ["BOS", "BWI"]
    assert clarification.raw_value == "BOH"
    assert "stations" in clarification.guessed_categories


def test_stop_words_not_flagged():
    """Common words should not be treated as unknown entities."""
    q = "what is the attrition rate for this quarter"
    consumed = set()
    candidates = _extract_candidates(q, consumed)

    # "what", "is", "the", "attrition", "rate", "for", "this", "quarter" are all stop words
    assert "what" not in candidates
    assert "is" not in candidates
    assert "the" not in candidates
    assert "attrition" not in candidates
    assert "rate" not in candidates
    assert "for" not in candidates
    assert "this" not in candidates
    assert "quarter" not in candidates


def test_no_native_categories_means_no_check():
    """If KPI has no native dimension rules, skip unknown detection."""
    extraction = ExtractionResult(
        original_question="What is attrition for BOH?",
        detected_kpi="Attrition Rate",
        detected_terms={},
    )
    recipe = KPIRecipe(
        id="kpi_attrition",
        name="Attrition Rate",
        description="",
        complexity="simple",
        formula="",
        dimension_rules={
            "customers": {
                "filterable": False,
                "groupable": False,
                "support_type": "unsupported",
                "reason": "Not supported",
            }
        },
    )

    result = detect_unknown_entities("What is attrition for BOH?", extraction, recipe)
    assert result is None
