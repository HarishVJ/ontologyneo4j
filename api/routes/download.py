"""
POST /api/v1/download — Re-execute a validated SQL query and stream the full result as CSV.
Called by the UI when has_more=True (result exceeded 50 rows).
"""

import csv
import io
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from core.snowflake_executor import execute_sql_csv
from core.sql_validator import validate_sql
from core.models import StructuredContext
from config.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


class DownloadRequest(BaseModel):
    sql: str = Field(..., description="Validated SQL to execute for full export")
    filename: str = Field(default="export.csv", description="Suggested filename for download")
    kpi_name: str = Field(default="export", description="KPI name for logging")
    view_name: str = Field(
        default="DIMFINANCEBUSINESSSTRUCTURE_V",
        description="View name for schema compliance check",
    )


@router.post("/api/v1/download")
async def download_csv(request: DownloadRequest):
    """Re-execute the given SQL without row limit and return as CSV download."""

    # Re-validate before executing — never trust client-supplied SQL without checks
    context = StructuredContext(
        kpi_name=request.kpi_name,
        kpi_id="download",
        formula="",
        views=[{
            "name": request.view_name,
            "alias": "b",
            "columns": [],  # column check skipped for download (already validated on ask)
            "schema": "AIRCO_EDW_UAT.ILINKAICHAT",
        }],
        schema_prefix="AIRCO_EDW_UAT.ILINKAICHAT",
    )
    validation = validate_sql(request.sql, context)
    if validation.status == "failed":
        raise HTTPException(status_code=400, detail={"errors": validation.errors})

    try:
        columns, rows = execute_sql_csv(request.sql)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Stream CSV
    def _generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        yield buf.getvalue()

        for row in rows:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([str(v) if v is not None else "" for v in row])
            yield buf.getvalue()

    logger.info("csv_download_started", kpi=request.kpi_name, rows=len(rows))

    safe_filename = request.filename.replace(" ", "_").replace("/", "_")
    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "X-Row-Count": str(len(rows)),
        },
    )
