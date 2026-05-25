"""
NL2SQL Ontology POC — FastAPI Application

Clean executive-ready API demonstrating the end-to-end pipeline:
    User Question → Intent Extraction → Neo4j Lookup →
    Context Builder → LLM SQL Generator → SQL Validator →
    Mock Executor → Final Answer
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from pipeline import NL2SQLPipeline


# ─── Request / Response Models ─────────────────────────────────
class AskRequest(BaseModel):
    question: str
    user_id: str = "anonymous"
    security_scope: Optional[dict] = None


# ─── Application Lifecycle ─────────────────────────────────────
pipeline: Optional[NL2SQLPipeline] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline
    try:
        pipeline = NL2SQLPipeline()
        print("✓ Pipeline initialized (Neo4j + LLM + Validator + Mock Executor)")
    except Exception as e:
        print(f"✗ Pipeline initialization failed: {e}")
        raise
    yield
    if pipeline:
        pipeline.close()
    print("✓ Pipeline shut down")


# ─── FastAPI App ───────────────────────────────────────────────
app = FastAPI(
    title="NL2SQL Ontology POC",
    description="Neo4j Ontology-Powered Natural Language to SQL",
    version="2.0.0",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── Endpoints ─────────────────────────────────────────────────
@app.get("/")
async def root():
    """Serve the main UI."""
    return FileResponse("static/index.html")


@app.post("/ask")
async def ask(request: AskRequest):
    """
    Main endpoint — run the full NL2SQL pipeline.

    Accepts a natural language question and returns:
    - Detected KPI and terms
    - Neo4j ontology context
    - Structured LLM context
    - Generated SQL
    - Validation result
    - Mock execution result
    - Final answer
    """
    result = pipeline.run(
        question=request.question,
        user_id=request.user_id,
        security_scope=request.security_scope,
    )
    return result


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "components": ["neo4j", "llm", "validator", "mock_executor"]}


@app.get("/examples")
async def examples():
    """Return example questions for the UI."""
    return {
        "examples": [
            {
                "question": "Show me headcount at ATL",
                "description": "Simple KPI — single view, single filter",
                "complexity": "simple",
            },
            {
                "question": "What is the attrition rate at ATL last month?",
                "description": "Complex KPI — 5 computation steps, 3 views, business rules",
                "complexity": "complex",
            },
            {
                "question": "What's the headcount at JFK?",
                "description": "Simple KPI — natural phrasing with apostrophe",
                "complexity": "simple",
            },
        ],
        "default_security_scope": {
            "stations": ["ATL", "JFK", "LGA"],
            "customers": ["DL", "UA"],
        },
    }
