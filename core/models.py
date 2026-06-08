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
    value_kind: str | None = None  # code | canonical | sql_expr | threshold


@dataclass
class ThresholdFilter:
    metric: str
    operator: str
    value: str
    sql_expr: str


@dataclass
class ExtractionResult:
    original_question: str
    detected_kpi: str | None = None
    detected_kpi_id: str | None = None
    detected_terms: dict[str, DetectedTerm] = field(default_factory=dict)
    detected_period: str | None = None
    detected_grouping: list[str] = field(default_factory=list)
    detected_aggregation: str | None = None
    detected_limit: int | None = None
    detected_thresholds: list[ThresholdFilter] = field(default_factory=list)
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
    supported_term_categories: list[str] = field(default_factory=list)  # empty = accept all
    default_ranking_metric: str | None = None  # for top-N
    default_ranking_order: str = "DESC"       # ASC or DESC
    version: str = "1.0"
    status: str = "active"
    grain: list[str] = field(default_factory=list)
    dimension_rules: dict[str, Any] = field(default_factory=dict)
    required_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClarificationRequest:
    required_field: str
    question: str
    options: list[str] = field(default_factory=list)
    reason: str | None = None
    raw_value: str | None = None
    guessed_categories: list[str] = field(default_factory=list)


@dataclass
class UnknownEntityCandidate:
    raw_text: str
    guessed_categories: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    reason: str | None = None


@dataclass
class RequirementCheckResult:
    status: str
    clarification: ClarificationRequest | None = None
    unsupported_reason: str | None = None


@dataclass
class ViewMetadata:
    name: str
    schema: str
    alias: str
    columns: list[str] = field(default_factory=list)
    approved_aliases: list[str] = field(default_factory=list)
    date_column: str | None = None
    unsupported_term_categories: list[str] = field(default_factory=list)


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
    grouping: list[str] = field(default_factory=list)
    limit: int | None = None
    thresholds: list[str] = field(default_factory=list)


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
    clarification_required: bool = False
    clarification: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    latency_ms: dict[str, float] = field(default_factory=dict)
