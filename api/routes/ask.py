"""POST /api/v1/ask — Main query endpoint."""

from dataclasses import asdict
from fastapi import APIRouter, Request
from api.schemas.request import AskRequest
from api.schemas.response import AskResponse

router = APIRouter()


@router.post("/api/v1/ask", response_model=AskResponse)
async def ask(request: AskRequest, req: Request):
    """Process a natural language question through the NL2SQL pipeline."""
    pipeline = req.app.state.pipeline
    result = pipeline.ask(
        question=request.question,
        user_id=request.user_id,
        authorized_stations=request.authorized_stations,
    )
    return AskResponse(**asdict(result))
