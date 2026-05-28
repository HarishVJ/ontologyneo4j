"""Pydantic request models for the API."""

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500, description="Natural language question")
    user_id: str = Field(default="demo_user", description="User identifier for RLS")
    authorized_stations: list[str] | None = Field(
        default=None, description="Authorized station codes for this user (overrides role lookup)"
    )

    model_config = {"json_schema_extra": {"examples": [{"question": "List all contracts for MSP"}]}}
