"""
Golden test runner: loads test cases from YAML and validates pipeline output.
Usage: pytest tests/test_golden.py -v
"""

import yaml
import pytest
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent / "golden"


def load_golden_cases():
    cases = []
    for yaml_file in GOLDEN_DIR.glob("*.yaml"):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        for test in data.get("tests", []):
            cases.append(pytest.param(test, id=test["id"]))
    return cases


@pytest.fixture(scope="module")
def pipeline():
    from core.pipeline import NL2SQLPipeline
    return NL2SQLPipeline()


@pytest.mark.parametrize("case", load_golden_cases())
def test_golden_extraction(case, pipeline):
    """Verify intent extraction matches expected KPI and terms."""
    from core.intent_extractor import extract

    result = extract(case["question"])

    # Check KPI detection
    assert result.detected_kpi == case["expected_kpi"], (
        f"Question: {case['question']}\n"
        f"Expected KPI: {case['expected_kpi']}, Got: {result.detected_kpi}"
    )

    # Check term detection
    expected_terms = case.get("expected_terms", {})
    for category, value in expected_terms.items():
        found = False
        for term_key, term in result.detected_terms.items():
            if term.category == category and (term.value == value or term_key == value):
                found = True
                break
        assert found, (
            f"Question: {case['question']}\n"
            f"Expected term {category}={value} not found in {result.detected_terms}"
        )


@pytest.mark.parametrize("case", load_golden_cases())
def test_golden_sql_generation(case, pipeline):
    """Verify generated SQL contains expected patterns."""
    response = pipeline.ask(case["question"])

    assert response.sql is not None, f"No SQL generated for: {case['question']}"

    for pattern in case.get("expected_sql_contains", []):
        assert pattern.upper() in response.sql.upper(), (
            f"Question: {case['question']}\n"
            f"Expected '{pattern}' in SQL but not found.\nSQL: {response.sql}"
        )

    for pattern in case.get("expected_sql_not_contains", []):
        assert pattern.upper() not in response.sql.upper(), (
            f"Question: {case['question']}\n"
            f"Forbidden '{pattern}' found in SQL.\nSQL: {response.sql}"
        )
