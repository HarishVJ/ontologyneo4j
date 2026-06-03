"""
Lean ontology pipeline orchestrator.

Stages:
    1. plan_extractor.extract_plan(question)        — LLM call #1
    2. sql_composer.resolve_metric_specs(plan)      — Neo4j join-path queries
    3. sql_composer.compose_sql(plan, specs)        — LLM call #2
    4. sql_validator.validate_sql(sql, specs, …)    — guardrails
    5. snowflake_executor.execute_sql(sql)          — execution
    6. format_answer(plan, rows)                    — narrative response
"""

import time
from dataclasses import asdict
from core.models import PipelineResponse, Plan
from core.plan_extractor import extract_plan
from core.sql_composer import resolve_metric_specs, compose_sql
from core.sql_validator import validate_sql
from core.snowflake_executor import execute_sql
from core.neo4j_client import verify_connectivity
from core.ontology_queries import fetch_metric_catalog, fetch_terms
from config.logging_config import get_logger

logger = get_logger(__name__)


class NL2SQLPipeline:
    """Wires plan extraction → SQL composition → validation → execution."""

    def __init__(self):
        logger.info("pipeline_initializing")
        if not verify_connectivity():
            raise RuntimeError("Cannot connect to Neo4j — pipeline initialization failed")

        # Warm the ontology caches so the first request is fast.
        catalog = fetch_metric_catalog()
        terms = fetch_terms()
        if not catalog:
            raise RuntimeError(
                "Neo4j has no metrics — run `python -m scripts.seed_ontology`"
            )
        logger.info(
            "pipeline_ready",
            metrics=len(catalog),
            term_categories=len({t["category"] for t in terms}),
        )

    # ── Public ────────────────────────────────────────────────────

    def ask(
        self,
        question: str,
        user_id: str = "demo_user",
        authorized_stations: list[str] | None = None,
    ) -> PipelineResponse:
        latency: dict[str, float] = {}
        total_start = time.time()

        try:
            # 1. Plan extraction
            t0 = time.time()
            plan: Plan = extract_plan(question)
            latency["plan_ms"] = round((time.time() - t0) * 1000, 1)

            if not plan.metrics or plan.confidence < 0.4:
                return self._unrecognized_response(question, plan, latency)

            # 2. Resolve metric specs (Neo4j join-path queries)
            t0 = time.time()
            specs = resolve_metric_specs(plan)
            latency["resolve_ms"] = round((time.time() - t0) * 1000, 1)

            # 3. SQL composition
            t0 = time.time()
            sql = compose_sql(plan, specs)
            latency["compose_ms"] = round((time.time() - t0) * 1000, 1)

            # 4. Validation
            t0 = time.time()
            validation = validate_sql(sql, specs, user_id=user_id, authorized_stations=authorized_stations)
            latency["validation_ms"] = round((time.time() - t0) * 1000, 1)

            # 5. Execution (only if validation passed)
            execution: dict = {}
            if validation.status == "passed":
                t0 = time.time()
                execution = execute_sql(sql)
                latency["execution_ms"] = round((time.time() - t0) * 1000, 1)
            else:
                execution = {"error": "Blocked — SQL validation failed", "rows": [], "row_count": 0}

            answer = self._format_answer(plan, execution)
            latency["total_ms"] = round((time.time() - total_start) * 1000, 1)

            return PipelineResponse(
                question=question,
                answer=answer,
                plan=plan.to_dict(),
                metrics_resolved=[
                    {
                        "id": s.id,
                        "kind": s.kind,
                        "view": s.view.name,
                        "join_chains": {
                            dim: [
                                {"join_id": h.join_id, "from": h.from_view, "to": h.to_view}
                                for h in ch.hops
                            ]
                            for dim, ch in s.join_chains.items()
                        },
                    }
                    for s in specs
                ],
                sql=sql,
                validation=asdict(validation),
                execution=execution,
                has_more=execution.get("has_more", False),
                latency_ms=latency,
            )

        except Exception as e:
            latency["total_ms"] = round((time.time() - total_start) * 1000, 1)
            logger.error("pipeline_error", error=str(e), question=question)
            return self._error_response(question, str(e), latency)

    # ── Helpers ───────────────────────────────────────────────────

    def _unrecognized_response(
        self, question: str, plan: Plan, latency: dict
    ) -> PipelineResponse:
        catalog = fetch_metric_catalog()
        names = [m["name"] for m in catalog]
        answer = (
            f"I couldn't confidently match your question to a metric. "
            f"Available metrics: {', '.join(names)}. "
            f"{plan.notes or ''}"
        )
        return PipelineResponse(
            question=question, answer=answer.strip(),
            plan=plan.to_dict(), latency_ms=latency,
        )

    def _error_response(self, question: str, error: str, latency: dict) -> PipelineResponse:
        return PipelineResponse(
            question=question,
            answer=f"Sorry, I encountered an error: {error}",
            error=error, latency_ms=latency,
        )

    def _format_answer(self, plan: Plan, execution: dict) -> str:
        if execution.get("error"):
            return f"Query could not be executed: {execution['error']}"
        rows = execution.get("rows", [])
        row_count = execution.get("row_count", 0)
        has_more = execution.get("has_more", False)
        if not rows:
            return "No results found for your query."
        # Single scalar row → unwrap
        if row_count == 1 and len(rows[0]) == 1:
            return f"Result: {list(rows[0].values())[0]}"
        if has_more:
            return (
                f"Showing first {row_count} results — there are more records. "
                f"Use the Download CSV button to get the full dataset."
            )
        return f"Found {row_count} result(s)."
