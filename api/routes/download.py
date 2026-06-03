"""
POST /api/v1/download — Re-execute a validated SQL query and stream the full result as CSV.
Called by the UI when has_more=True (result exceeded 50 rows).
"""

import csv
import io
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse
from core.snowflake_executor import execute_sql_csv
from core.sql_validator import validate_sql
from core.sql_composer import resolve_metric_specs
from core.models import Plan, PlanMetric
from config.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


class DownloadRequest(BaseModel):
    sql: str = Field(..., description="Validated SQL to execute for full export")
    filename: str = Field(default="export.csv", description="Suggested filename for download")
    metric_ids: list[str] = Field(
        default_factory=list,
        description="Metric IDs the SQL was composed for; used to rebuild the validator allowlist",
    )
    group_by: list[str] = Field(
        default_factory=list,
        description="Group-by columns the original plan used (so join-chain views are allowlisted)",
    )


@router.post("/api/v1/download")
async def download_csv(request: DownloadRequest):
    """Re-validate against the original metric specs and stream CSV."""

    if not request.metric_ids:
        raise HTTPException(
            status_code=400,
            detail={"errors": ["metric_ids required to rebuild the SQL validator allowlist"]},
        )

    plan = Plan(
        output="aggregate",
        metrics=[PlanMetric(id=mid) for mid in request.metric_ids],
        group_by=list(request.group_by),
    )
    try:
        specs = resolve_metric_specs(plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"errors": [str(e)]})

    validation = validate_sql(request.sql, specs)
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

    logger.info("csv_download_started", metrics=request.metric_ids, rows=len(rows))

    safe_filename = request.filename.replace(" ", "_").replace("/", "_")
    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "X-Row-Count": str(len(rows)),
        },
    )
