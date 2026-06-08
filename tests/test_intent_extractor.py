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
    assert any(t.value == "MSP" for t in result.detected_terms.values())


def test_detect_count_contracts():
    from core.intent_extractor import extract
    result = extract("How many contracts are there?")
    assert result.detected_kpi == "Count Contracts"


def test_detect_station():
    from core.intent_extractor import extract
    result = extract("Show contracts at ATL")
    assert any(t.category == "stations" for t in result.detected_terms.values())
    assert any(t.value == "ATL" for t in result.detected_terms.values())


def test_detect_customer():
    from core.intent_extractor import extract
    result = extract("What contracts does Delta have?")
    found_customer = any(t.category == "customers" for t in result.detected_terms.values())
    assert found_customer


def test_detect_division():
    from core.intent_extractor import extract
    result = extract("List contracts for Security division")
    found_div = any(t.category == "divisions" for t in result.detected_terms.values())
    assert found_div


def test_detect_cost_center():
    from core.intent_extractor import extract
    result = extract("Provide the contract name for cost center 641")
    found_cc = any(t.category == "costcenter" for t in result.detected_terms.values())
    assert found_cc


def test_detect_status_filter():
    from core.intent_extractor import extract
    result = extract("Show active employees at MSP")
    found_status = any(t.category == "employment_status" for t in result.detected_terms.values())
    assert found_status


def test_detect_employment_type():
    from core.intent_extractor import extract
    result = extract("How many full-time employees?")
    found_type = any(t.category == "employment_type" for t in result.detected_terms.values())
    assert found_type


def test_detect_pay_code():
    from core.intent_extractor import extract
    result = extract("Show overtime hours for MSP")
    found_pay = any(t.category == "pay_code" for t in result.detected_terms.values())
    assert found_pay


def test_detect_grouping():
    from core.intent_extractor import extract
    result = extract("Employee count by station")
    assert "STATIONCODE" in result.detected_grouping


def test_detect_time_grouping():
    from core.intent_extractor import extract
    result = extract("Overtime trend by month")
    assert any("DATE_TRUNC('month'" in g for g in result.detected_grouping)


def test_detect_top_n():
    from core.intent_extractor import extract
    result = extract("Top 5 stations by employee count")
    assert result.detected_limit == 5


def test_date_parser_month_year():
    from core.date_parser import parse_period
    sql = parse_period("Dec '25")
    assert sql is not None
    assert "{date_col}" in sql
    assert "2025-12-01" in sql


def test_date_parser_relative():
    from core.date_parser import parse_period
    sql = parse_period("last 6 months")
    assert sql is not None
    assert "DATEADD(month, -6" in sql


def test_detect_threshold_percentage():
    from core.intent_extractor import extract
    result = extract("Attrition rate more than 10%")
    assert len(result.detected_thresholds) == 1
    assert result.detected_thresholds[0].sql_expr == "ATTRITION_RATE_PCT > 10"


def test_detect_threshold_hours():
    from core.intent_extractor import extract
    result = extract("Overtime exceeding 40 hours")
    assert len(result.detected_thresholds) == 1
    assert result.detected_thresholds[0].sql_expr == "TOTAL_HOURS > 40"


def test_detect_threshold_employees():
    from core.intent_extractor import extract
    result = extract("Employee count over 1000")
    assert len(result.detected_thresholds) == 1
    assert result.detected_thresholds[0].sql_expr == "EMPLOYEE_COUNT > 1000"


def test_detect_multi_value_stations():
    from core.intent_extractor import extract
    result = extract("Show contracts at MSP and ATL")
    station_terms = [t for t in result.detected_terms.values() if t.category == "stations"]
    assert len(station_terms) == 2


def test_entity_by_name_match():
    from core.intent_extractor import extract
    # If "Atlanta" is a canonical name for ATL, it should resolve to ATL
    result = extract("Contracts in Atlanta")
    station_terms = [t for t in result.detected_terms.values() if t.category == "stations"]
    assert len(station_terms) >= 1
    assert any(t.value == "ATL" for t in station_terms)


def test_unknown_question_returns_none_kpi():
    from core.intent_extractor import extract
    result = extract("What is the weather today?")
    assert result.detected_kpi is None
