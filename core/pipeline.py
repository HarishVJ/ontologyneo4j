"""
Pipeline orchestrator: wires all components together in sequence.
Each step is timed and its output captured for full audit trail.
"""

import time
from dataclasses import asdict
from core.models import PipelineResponse, ExtractionResult
from core.intent_extractor import extract, load_terms_from_neo4j
from core.ontology_lookup import lookup_kpi, get_all_active_kpis
from core.context_builder import build_context
from core.requirement_checker import check_requirements
from core.unknown_entity_detector import detect_unknown_entities, to_clarification
from core.sql_generator import generate_sql
from core.sql_validator import validate_sql
from core.snowflake_executor import execute_sql
from core.neo4j_client import verify_connectivity
from config.logging_config import get_logger

logger = get_logger(__name__)


class NL2SQLPipeline:
    """Orchestrates the full NL2SQL pipeline."""

    def __init__(self):
        """Initialize pipeline: verify Neo4j, load terms."""
        logger.info("pipeline_initializing")

        if not verify_connectivity():
            raise RuntimeError("Cannot connect to Neo4j — pipeline initialization failed")

        load_terms_from_neo4j()
        logger.info("pipeline_ready")

    def ask(
        self,
        question: str,
        user_id: str = "demo_user",
        authorized_stations: list[str] | None = None,
    ) -> PipelineResponse:
        """Process a natural language question through the full pipeline."""
        latency = {}
        total_start = time.time()

        try:
            # Step 1: Intent Extraction
            t0 = time.time()
            extraction = extract(question)
            latency["extraction_ms"] = round((time.time() - t0) * 1000, 1)

            if not extraction.detected_kpi:
                return self._unrecognized_response(question, extraction, latency)

            # Step 2: Ontology Lookup
            t0 = time.time()
            recipe = lookup_kpi(extraction.detected_kpi)
            latency["neo4j_ms"] = round((time.time() - t0) * 1000, 1)

            if not recipe:
                return self._error_response(
                    question, f"KPI '{extraction.detected_kpi}' not found in ontology", latency
                )

            # Step 3: Unknown Entity Detection
            t0 = time.time()
            unknown = detect_unknown_entities(question, extraction, recipe)
            latency["unknown_entity_ms"] = round((time.time() - t0) * 1000, 1)

            if unknown:
                clarification = to_clarification(unknown)
                return PipelineResponse(
                    question=question,
                    answer=clarification.question,
                    detected_kpi=extraction.detected_kpi,
                    extraction=asdict(extraction),
                    neo4j_context={"kpi_id": recipe.id, "views": recipe.views, "steps": len(recipe.steps)},
                    clarification_required=True,
                    clarification=asdict(clarification),
                    latency_ms=latency,
                )

            # Step 4: Requirement Check
            t0 = time.time()
            requirement_check = check_requirements(extraction, recipe)
            latency["requirements_ms"] = round((time.time() - t0) * 1000, 1)

            if requirement_check.status == "clarification" and requirement_check.clarification:
                return PipelineResponse(
                    question=question,
                    answer=requirement_check.clarification.question,
                    detected_kpi=extraction.detected_kpi,
                    extraction=asdict(extraction),
                    neo4j_context={"kpi_id": recipe.id, "views": recipe.views, "steps": len(recipe.steps)},
                    clarification_required=True,
                    clarification=asdict(requirement_check.clarification),
                    latency_ms=latency,
                )

            if requirement_check.status == "unsupported":
                return PipelineResponse(
                    question=question,
                    answer=requirement_check.unsupported_reason or "This request is not supported for the selected KPI.",
                    detected_kpi=extraction.detected_kpi,
                    extraction=asdict(extraction),
                    neo4j_context={"kpi_id": recipe.id, "views": recipe.views, "steps": len(recipe.steps)},
                    error=requirement_check.unsupported_reason,
                    latency_ms=latency,
                )

            # Step 5: Context Building
            t0 = time.time()
            context = build_context(extraction, recipe)
            latency["context_ms"] = round((time.time() - t0) * 1000, 1)

            # Step 6: SQL Generation
            t0 = time.time()
            sql = generate_sql(context)
            latency["llm_ms"] = round((time.time() - t0) * 1000, 1)

            # Step 7: SQL Validation
            t0 = time.time()
            validation = validate_sql(sql, context, authorized_stations)
            latency["validation_ms"] = round((time.time() - t0) * 1000, 1)

            # Step 8: Execution (only if validation passed)
            execution_result = {}
            if validation.status == "passed":
                t0 = time.time()
                execution_result = execute_sql(sql)
                latency["execution_ms"] = round((time.time() - t0) * 1000, 1)
            else:
                execution_result = {"error": "Blocked — SQL validation failed", "rows": []}

            # Build answer
            has_more = execution_result.get("has_more", False)
            answer = self._format_answer(extraction, execution_result)

            latency["total_ms"] = round((time.time() - total_start) * 1000, 1)

            return PipelineResponse(
                question=question,
                answer=answer,
                detected_kpi=extraction.detected_kpi,
                sql=sql,
                extraction=asdict(extraction),
                neo4j_context={"kpi_id": recipe.id, "views": recipe.views, "steps": len(recipe.steps)},
                structured_context={
                    "kpi": context.kpi_name,
                    "filters": context.filters,
                    "output_columns": context.output_columns,
                },
                validation=asdict(validation),
                execution=execution_result,
                has_more=has_more,
                latency_ms=latency,
            )

        except Exception as e:
            latency["total_ms"] = round((time.time() - total_start) * 1000, 1)
            logger.error("pipeline_error", error=str(e), question=question)
            return self._error_response(question, str(e), latency)

    def _unrecognized_response(
        self, question: str, extraction: ExtractionResult, latency: dict
    ) -> PipelineResponse:
        """Handle questions where no KPI was detected."""
        active_kpis = get_all_active_kpis()
        kpi_names = [k["name"] for k in active_kpis]
        answer = (
            f"I couldn't identify a specific query type from your question. "
            f"I can help with: {', '.join(kpi_names)}. "
            f"Try asking something like 'List all contracts for MSP' or 'How many contracts are in the Security division?'"
        )
        return PipelineResponse(
            question=question,
            answer=answer,
            extraction=asdict(extraction),
            latency_ms=latency,
        )

    def _error_response(self, question: str, error: str, latency: dict) -> PipelineResponse:
        return PipelineResponse(
            question=question,
            answer=f"Sorry, I encountered an error: {error}",
            error=error,
            latency_ms=latency,
        )

    def _format_answer(self, extraction: ExtractionResult, result: dict) -> str:
        """Format execution result into a natural language answer."""
        if result.get("error"):
            return f"Query could not be executed: {result['error']}"

        rows = result.get("rows", [])
        row_count = result.get("row_count", 0)
        has_more = result.get("has_more", False)

        if not rows:
            return "No results found for your query."

        # For aggregate queries (count) — single-cell result
        if row_count == 1 and len(rows[0]) <= 2:
            values = list(rows[0].values())
            if len(values) == 1:
                return f"Result: {values[0]}"

        if has_more:
            return (
                f"Showing first 50 results — there are more records. "
                f"Use the Download CSV button to get the full dataset."
            )
        return f"Found {row_count} result(s)."
