"""Pydantic response models for the API."""

from pydantic import BaseModel
from typing import Any


class AskResponse(BaseModel):
    question: str
    answer: str
    plan: dict[str, Any] = {}
    metrics_resolved: list[dict[str, Any]] = []
    sql: str | None = None
    validation: dict[str, Any] = {}
    execution: dict[str, Any] = {}
    has_more: bool = False
    error: str | None = None
    latency_ms: dict[str, float] = {}


class HealthResponse(BaseModel):
    status: str
    neo4j: str
    version: str = "2.0.0"


class ExampleResponse(BaseModel):
    examples: list[dict[str, str]]
