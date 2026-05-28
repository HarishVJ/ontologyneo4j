"""Health and readiness endpoints."""

from fastapi import APIRouter
from api.schemas.response import HealthResponse, ExampleResponse
from core.neo4j_client import verify_connectivity

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health():
    """Basic health check."""
    neo4j_ok = verify_connectivity()
    return HealthResponse(
        status="healthy" if neo4j_ok else "degraded",
        neo4j="connected" if neo4j_ok else "disconnected",
    )


@router.get("/ready")
async def ready():
    """Readiness probe — returns 200 only if all dependencies are reachable."""
    neo4j_ok = verify_connectivity()
    if not neo4j_ok:
        return {"status": "not_ready", "reason": "Neo4j unreachable"}, 503
    return {"status": "ready"}


@router.get("/api/v1/examples", response_model=ExampleResponse)
async def examples():
    """Return sample questions for the UI."""
    return ExampleResponse(examples=[
        {"question": "List all contracts for MSP", "category": "contracts"},
        {"question": "How many contracts are there in the Security division?", "category": "contracts"},
        {"question": "List all the stations", "category": "stations"},
        {"question": "List all contracts for Central region", "category": "contracts"},
        {"question": "Provide the contract name for cost center 641", "category": "hierarchy"},
        {"question": "List all customers at ATL", "category": "customers"},
        {"question": "What contracts does Delta have?", "category": "contracts"},
        {"question": "List all the airports", "category": "stations"},
    ])
