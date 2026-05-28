"""
Domain models for the NL2SQL pipeline.
All structured data flows through these dataclasses.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DetectedTerm:
    category: str
    value: str
    column: str | None = None


@dataclass
class ExtractionResult:
    original_question: str
    detected_kpi: str | None = None
    detected_kpi_id: str | None = None
    detected_terms: dict[str, DetectedTerm] = field(default_factory=dict)
    detected_period: str | None = None
    detected_grouping: str | None = None
    detected_aggregation: str | None = None
    confidence: float = 1.0


@dataclass
class KPIStep:
    order: int
    name: str
    logic: str
    required_columns: list[str] = field(default_factory=list)


@dataclass
class KPIFilter:
    column: str
    source: str
    operator: str = "="
    value: str | None = None


@dataclass
class OutputShape:
    type: str
    columns: list[str] = field(default_factory=list)
    order_by: list[str] = field(default_factory=list)


@dataclass
class KPIRecipe:
    id: str
    name: str
    description: str
    complexity: str
    formula: str
    views: list[str] = field(default_factory=list)
    steps: list[KPIStep] = field(default_factory=list)
    filters: list[KPIFilter] = field(default_factory=list)
    output_shape: OutputShape | None = None
    version: str = "1.0"
    status: str = "active"


@dataclass
class ViewMetadata:
    name: str
    schema: str
    alias: str
    columns: list[str] = field(default_factory=list)


@dataclass
class StructuredContext:
    kpi_name: str
    kpi_id: str
    formula: str
    views: list[dict[str, Any]] = field(default_factory=list)
    joins: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    output_columns: list[str] = field(default_factory=list)
    order_by: list[str] = field(default_factory=list)
    schema_prefix: str = ""
    grouping: str | None = None


@dataclass
class ValidationResult:
    status: str  # "passed" or "failed"
    checks: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class PipelineResponse:
    question: str
    answer: str
    detected_kpi: str | None = None
    sql: str | None = None
    extraction: dict[str, Any] = field(default_factory=dict)
    neo4j_context: dict[str, Any] = field(default_factory=dict)
    structured_context: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    has_more: bool = False
    error: str | None = None
    latency_ms: dict[str, float] = field(default_factory=dict)
