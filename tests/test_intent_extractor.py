"""Unit tests for intent extractor (requires Neo4j terms to be loaded)."""

import pytest


@pytest.fixture(scope="module", autouse=True)
def load_terms():
    from core.intent_extractor import load_terms_from_neo4j
    load_terms_from_neo4j()


def test_detect_list_contracts():
    from core.intent_extractor import extract
    result = extract("List all contracts for MSP")
    assert result.detected_kpi == "List Contracts"
    assert "MSP" in result.detected_terms


def test_detect_count_contracts():
    from core.intent_extractor import extract
    result = extract("How many contracts are there?")
    assert result.detected_kpi == "Count Contracts"


def test_detect_station():
    from core.intent_extractor import extract
    result = extract("Show contracts at ATL")
    assert "ATL" in result.detected_terms
    assert result.detected_terms["ATL"].category == "station"


def test_detect_customer():
    from core.intent_extractor import extract
    result = extract("What contracts does Delta have?")
    found_customer = any(t.category == "customer" for t in result.detected_terms.values())
    assert found_customer


def test_detect_division():
    from core.intent_extractor import extract
    result = extract("List contracts for Security division")
    found_div = any(t.category == "division" for t in result.detected_terms.values())
    assert found_div


def test_detect_cost_center():
    from core.intent_extractor import extract
    result = extract("Provide the contract name for cost center 641")
    found_cc = any(t.category == "costcenter" for t in result.detected_terms.values())
    assert found_cc


def test_unknown_question_returns_none_kpi():
    from core.intent_extractor import extract
    result = extract("What is the weather today?")
    assert result.detected_kpi is None
