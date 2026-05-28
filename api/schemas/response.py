"""Pydantic response models for the API."""

from pydantic import BaseModel
from typing import Any


class AskResponse(BaseModel):
    question: str
    answer: str
    detected_kpi: str | None = None
    sql: str | None = None
    extraction: dict[str, Any] = {}
    neo4j_context: dict[str, Any] = {}
    structured_context: dict[str, Any] = {}
    validation: dict[str, Any] = {}
    execution: dict[str, Any] = {}
    has_more: bool = False
    error: str | None = None
    latency_ms: dict[str, float] = {}


class HealthResponse(BaseModel):
    status: str
    neo4j: str
    version: str = "1.0.0"


class ExampleResponse(BaseModel):
    examples: list[dict[str, str]]
