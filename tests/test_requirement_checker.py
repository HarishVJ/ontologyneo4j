from core.models import DetectedTerm, ExtractionResult, KPIRecipe
from core.requirement_checker import check_requirements


def test_optional_scope_allows_overall_attrition():
    extraction = ExtractionResult(
        original_question="What is attrition this quarter?",
        detected_kpi="Attrition Rate",
        detected_period="DATE >= DATE_TRUNC('QUARTER', CURRENT_DATE)",
    )
    recipe = KPIRecipe(
        id="kpi_attrition_rate_simple",
        name="Attrition Rate",
        description="",
        complexity="medium",
        formula="",
        required_context={
            "scope": {
                "required": False,
                "one_of": ["stations", "costcenter"],
                "clarification_prompt": "Do you want attrition for a specific station or cost center?",
            }
        },
    )

    result = check_requirements(extraction, recipe)

    assert result.status == "ok"


def test_required_scope_returns_clarification():
    extraction = ExtractionResult(
        original_question="What is attrition this quarter?",
        detected_kpi="Attrition Rate",
        detected_period="DATE >= DATE_TRUNC('QUARTER', CURRENT_DATE)",
    )
    recipe = KPIRecipe(
        id="kpi_attrition_rate_simple",
        name="Attrition Rate",
        description="",
        complexity="medium",
        formula="",
        required_context={
            "scope": {
                "required": True,
                "one_of": ["stations", "costcenter"],
                "clarification_prompt": "Do you want attrition for a specific station or cost center?",
            }
        },
    )

    result = check_requirements(extraction, recipe)

    assert result.status == "clarification"
    assert result.clarification is not None
    assert result.clarification.options == ["stations", "costcenter"]


def test_unsupported_dimension_returns_reason():
    extraction = ExtractionResult(
        original_question="Show attrition by customer",
        detected_kpi="Attrition Rate",
        detected_grouping=["customers"],
    )
    recipe = KPIRecipe(
        id="kpi_attrition_rate_simple",
        name="Attrition Rate",
        description="",
        complexity="medium",
        formula="",
        dimension_rules={
            "customers": {
                "filterable": False,
                "groupable": False,
                "support_type": "unsupported",
                "reason": "Attrition data is aggregated by date, station, and cost center; customer grain is not available.",
            }
        },
    )

    result = check_requirements(extraction, recipe)

    assert result.status == "unsupported"
    assert "customer grain is not available" in result.unsupported_reason


def test_station_scope_satisfies_requirement():
    extraction = ExtractionResult(
        original_question="What is attrition for ATL this quarter?",
        detected_kpi="Attrition Rate",
        detected_period="DATE >= DATE_TRUNC('QUARTER', CURRENT_DATE)",
        detected_terms={
            "stations_ATL": DetectedTerm(category="stations", value="ATL", column="STATIONCODE", value_kind="code")
        },
    )
    recipe = KPIRecipe(
        id="kpi_attrition_rate_simple",
        name="Attrition Rate",
        description="",
        complexity="medium",
        formula="",
        required_context={
            "scope": {
                "required": True,
                "one_of": ["stations", "costcenter"],
                "clarification_prompt": "Do you want attrition for a specific station or cost center?",
            }
        },
    )

    result = check_requirements(extraction, recipe)

    assert result.status == "ok"
