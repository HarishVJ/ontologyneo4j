"""
Domain models for the lean ontology pipeline.

Every stage of the pipeline produces or consumes a `Plan` (the intermediate
representation extracted from the user question) and the resolved
`MetricSpec` objects (the YAML-driven semantic definitions plus the join
chain computed via Neo4j).
"""

from dataclasses import dataclass, field
from typing import Any


# ─── Plan ──────────────────────────────────────────────────────────────


@dataclass
class Threshold:
    op: str           # > >= < <= = !=
    value: float


@dataclass
class PlanMetric:
    id: str
    threshold: Threshold | None = None


@dataclass
class Filter:
    column: str
    op: str           # = != in like
    value: Any        # str | list[str] | number


@dataclass
class Ranking:
    by_metric: str
    direction: str    # ASC | DESC
    limit: int


@dataclass
class Period:
    expression: str   # already-substituted Snowflake predicate fragment


@dataclass
class Plan:
    """Structured representation of the user question."""

    output: str = "aggregate"      # aggregate | list
    metrics: list[PlanMetric] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)
    period: Period | None = None
    ranking: Ranking | None = None
    confidence: float = 1.0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "metrics": [
                {
                    "id": m.id,
                    "threshold": (
                        {"op": m.threshold.op, "value": m.threshold.value}
                        if m.threshold else None
                    ),
                }
                for m in self.metrics
            ],
            "group_by": list(self.group_by),
            "filters": [
                {"column": f.column, "op": f.op, "value": f.value}
                for f in self.filters
            ],
            "period": {"expression": self.period.expression} if self.period else None,
            "ranking": (
                {
                    "by_metric": self.ranking.by_metric,
                    "direction": self.ranking.direction,
                    "limit": self.ranking.limit,
                }
                if self.ranking else None
            ),
            "confidence": self.confidence,
            "notes": self.notes,
        }


# ─── Resolved metric specs (Plan + Neo4j) ──────────────────────────────


@dataclass
class JoinHop:
    join_id: str
    on: str           # join condition template with {from_alias}/{to_alias}
    type: str         # INNER | LEFT
    from_view: str
    to_view: str


@dataclass
class JoinChain:
    """Chain of hops from a metric's primary view to one target dimension."""

    target_dimension: str
    hops: list[JoinHop] = field(default_factory=list)
    end_view: str = ""             # final view in the chain (where dim lives)


@dataclass
class ViewMeta:
    name: str
    schema: str
    alias: str
    columns: list[str] = field(default_factory=list)
    approved_aliases: list[str] = field(default_factory=list)


@dataclass
class MetricSpec:
    """A YAML metric expanded with everything the SQL composer needs."""

    id: str
    kind: str                              # metric | list
    name: str
    description: str
    view: ViewMeta
    expression: str = ""
    alias: str = ""
    unit: str = ""
    polarity: str = ""
    list_columns: list[str] = field(default_factory=list)
    distinct_on: str = ""
    default_order_by: list[str] = field(default_factory=list)
    date_column: str = ""
    sliceable_by: list[str] = field(default_factory=list)
    join_chains: dict[str, JoinChain] = field(default_factory=dict)  # dim → chain


# ─── Validation & response ─────────────────────────────────────────────


@dataclass
class ValidationResult:
    status: str                            # passed | failed
    checks: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class PipelineResponse:
    question: str
    answer: str
    plan: dict[str, Any] = field(default_factory=dict)
    metrics_resolved: list[dict[str, Any]] = field(default_factory=list)
    sql: str | None = None
    validation: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    has_more: bool = False
    error: str | None = None
    latency_ms: dict[str, float] = field(default_factory=dict)
