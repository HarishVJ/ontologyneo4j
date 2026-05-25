"""
Pipeline Orchestrator

Responsibility: Orchestrate the end-to-end NL2SQL pipeline,
calling each component in sequence and assembling the final response.

Architecture Flow:
    User Question → Intent Extraction → Neo4j Lookup →
    Context Builder → LLM SQL Generator → SQL Validator →
    Mock Executor → Final Answer
"""

import time
from typing import Optional

from intent_extractor import extract, load_terms_from_neo4j, ExtractionResult
from neo4j_ontology import Neo4jOntology
from context_builder import build_context
from sql_generator import SQLGenerator
from sql_validator import SQLValidator
from mock_executor import execute_mock


class NL2SQLPipeline:
    """End-to-end NL2SQL pipeline orchestrator."""

    def __init__(self):
        self.ontology = Neo4jOntology()
        self.generator = SQLGenerator()
        self.validator = SQLValidator()
        self.view_aliases = self.ontology.get_view_aliases()
        # Load term dictionary from Neo4j (single source of truth)
        load_terms_from_neo4j()

    def close(self):
        self.ontology.close()

    def run(self, question: str, user_id: str = "anonymous", security_scope: Optional[dict] = None) -> dict:
        """
        Run the full pipeline and return a structured response showing
        each component's contribution.
        """
        start_time = time.time()
        security_scope = security_scope or {"stations": [], "customers": []}

        # ────────────────────────────────────────────────────
        # Step 1: Intent + Term Extraction (FastAPI backend)
        # ────────────────────────────────────────────────────
        extraction = extract(question)

        extraction_output = {
            "detected_kpi": extraction.detected_kpi,
            "detected_terms": {
                k: {"type": v.type, "value": v.value}
                for k, v in extraction.detected_terms.items()
            },
            "detected_period": None,
        }
        if extraction.detected_period:
            extraction_output["detected_period"] = {
                "type": extraction.detected_period.type,
                "start_date": extraction.detected_period.start_date,
                "end_date": extraction.detected_period.end_date,
                "days_in_period": extraction.detected_period.days_in_period,
            }

        if not extraction.detected_kpi:
            return self._error_response(
                question, extraction_output,
                "Could not detect a KPI from the question. Please ask about headcount, attrition, overtime, etc."
            )

        # Determine station filter
        station_filter = None
        for term_key, term_val in extraction.detected_terms.items():
            if term_val.type == "station":
                station_filter = term_val.value
                break

        # ────────────────────────────────────────────────────
        # Step 2: Neo4j Ontology Lookup
        # ────────────────────────────────────────────────────
        period_dict = None
        if extraction.detected_period:
            period_dict = {
                "start_date": extraction.detected_period.start_date,
                "end_date": extraction.detected_period.end_date,
                "days_in_period": extraction.detected_period.days_in_period,
            }

        neo4j_context = self.ontology.lookup_kpi(
            kpi_name=extraction.detected_kpi,
            station_filter=station_filter,
            period=period_dict,
        )

        if "error" in neo4j_context:
            return self._error_response(
                question, extraction_output, neo4j_context["error"]
            )

        # ────────────────────────────────────────────────────
        # Step 3: Structured Context Builder
        # ────────────────────────────────────────────────────
        structured_context = build_context(
            question=question,
            neo4j_result=neo4j_context,
            view_aliases=self.view_aliases,
            period=period_dict,
        )

        # ────────────────────────────────────────────────────
        # Step 4: LLM SQL Generator
        # ────────────────────────────────────────────────────
        generation_result = self.generator.generate(structured_context)
        generated_sql = generation_result.get("sql")

        if not generated_sql:
            return self._error_response(
                question, extraction_output,
                generation_result.get("error", "SQL generation failed")
            )

        # ────────────────────────────────────────────────────
        # Step 5: SQL Validator
        # ────────────────────────────────────────────────────
        validation = self.validator.validate(
            sql=generated_sql,
            allowed_columns=neo4j_context.get("allowed_columns", []),
            station_filter=station_filter,
            security_scope=security_scope,
        )

        # ────────────────────────────────────────────────────
        # Step 6: Mock Executor (only if validation passed)
        # ────────────────────────────────────────────────────
        if validation["status"] == "passed":
            execution = execute_mock(
                kpi_name=extraction.detected_kpi,
                station=station_filter,
            )
        else:
            execution = {
                "mock_result": None,
                "answer": "SQL failed validation — execution blocked.",
                "execution_mode": "blocked",
            }

        # ────────────────────────────────────────────────────
        # Assemble Final Response
        # ────────────────────────────────────────────────────
        elapsed_ms = round((time.time() - start_time) * 1000)

        detected_filters = {}
        if station_filter:
            detected_filters["station"] = station_filter
        if extraction.detected_period:
            detected_filters["period"] = extraction.detected_period.type

        return {
            "question": question,
            "detected_kpi": extraction.detected_kpi,
            "detected_filters": detected_filters,
            "components": {
                "intent_and_term_extraction": "FastAPI backend",
                "ontology_lookup": "Neo4j",
                "structured_context_builder": "Python backend service",
                "sql_generator": "LLM",
                "sql_validator": "Python backend validation layer",
                "execution": "Mock Snowflake executor",
            },
            "pipeline_steps": {
                "1_extraction": extraction_output,
                "2_neo4j_context": neo4j_context,
                "3_structured_context": structured_context,
                "4_generated_sql": generated_sql,
                "5_validation": validation,
                "6_execution": execution,
            },
            "generated_sql": generated_sql,
            "validation": {"status": validation["status"]},
            "mock_result": execution.get("mock_result"),
            "answer": execution.get("answer"),
            "elapsed_ms": elapsed_ms,
        }

    def _error_response(self, question: str, extraction: dict, error: str) -> dict:
        return {
            "question": question,
            "detected_kpi": extraction.get("detected_kpi"),
            "error": error,
            "pipeline_steps": {
                "1_extraction": extraction,
            },
            "components": {
                "intent_and_term_extraction": "FastAPI backend",
                "ontology_lookup": "Neo4j",
                "structured_context_builder": "Python backend service",
                "sql_generator": "LLM",
                "sql_validator": "Python backend validation layer",
                "execution": "Mock Snowflake executor",
            },
        }
