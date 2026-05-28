"""Unit tests for SQL validator."""

from core.sql_validator import validate_sql
from core.models import StructuredContext


def _make_context():
    return StructuredContext(
        kpi_name="List Contracts",
        kpi_id="kpi_list_contracts",
        formula="SELECT ...",
        views=[{
            "name": "DIMFINANCEBUSINESSSTRUCTURE_V",
            "alias": "b",
            "columns": [
                "CONTRACTCODE", "CONTRACTNAME", "STATIONCODE", "STATIONNAME",
                "CUSTOMERCODE", "CUSTOMERNAME", "DIVISIONNAME", "REGIONCODE",
                "GRANDPARENTREGIONNAME", "COSTCENTER",
            ],
            "schema": "AIRCO_EDW_UAT.ILINKAICHAT",
        }],
        schema_prefix="AIRCO_EDW_UAT.ILINKAICHAT",
    )


def test_valid_select():
    sql = "SELECT DISTINCT CONTRACTCODE, CONTRACTNAME FROM AIRCO_EDW_UAT.ILINKAICHAT.DIMFINANCEBUSINESSSTRUCTURE_V WHERE STATIONCODE = 'MSP'"
    result = validate_sql(sql, _make_context())
    assert result.status == "passed"


def test_rejects_drop():
    sql = "DROP TABLE DIMFINANCEBUSINESSSTRUCTURE_V"
    result = validate_sql(sql, _make_context())
    assert result.status == "failed"
    assert any("DROP" in e for e in result.errors)


def test_rejects_semicolon():
    sql = "SELECT 1; DROP TABLE x"
    result = validate_sql(sql, _make_context())
    assert result.status == "failed"


def test_rejects_unapproved_table():
    sql = "SELECT * FROM AIRCO_EDW_UAT.ILINKAICHAT.SOME_OTHER_TABLE"
    result = validate_sql(sql, _make_context())
    assert result.status == "failed"
    assert any("Unapproved" in e for e in result.errors)


def test_rls_blocks_unauthorized_station():
    sql = "SELECT CONTRACTCODE FROM AIRCO_EDW_UAT.ILINKAICHAT.DIMFINANCEBUSINESSSTRUCTURE_V WHERE STATIONCODE = 'LAX'"
    result = validate_sql(sql, _make_context(), authorized_stations=["ATL", "MSP"])
    assert result.status == "failed"
    assert any("Unauthorized" in e for e in result.errors)


def test_rls_allows_authorized_station():
    sql = "SELECT CONTRACTCODE FROM AIRCO_EDW_UAT.ILINKAICHAT.DIMFINANCEBUSINESSSTRUCTURE_V WHERE STATIONCODE = 'ATL'"
    result = validate_sql(sql, _make_context(), authorized_stations=["ATL", "MSP"])
    assert result.status == "passed"
