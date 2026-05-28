"""
FastAPI application factory with lifespan management.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.routes import ask, health, download
from core.pipeline import NL2SQLPipeline
from core.neo4j_client import close_driver
from core.snowflake_executor import warmup_connection, close_connection
from config.logging_config import setup_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    setup_logging()
    logger.info("application_starting")

    try:
        app.state.pipeline = NL2SQLPipeline()
        # Pre-warm Snowflake so first query is fast
        warmup_connection()
        logger.info("application_ready")
    except Exception as e:
        logger.error("application_startup_failed", error=str(e))
        app.state.pipeline = None

    yield

    # Shutdown
    close_connection()
    close_driver()
    logger.info("application_shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Unifi KPI Ontology-Enabled Chatbot",
        description="Neo4j ontology-powered NL2SQL engine for workforce analytics",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Register routes
    app.include_router(ask.router, tags=["Query"])
    app.include_router(download.router, tags=["Export"])
    app.include_router(health.router, tags=["System"])

    # Serve static files
    app.mount("/static", StaticFiles(directory="static"), name="static")

    @app.get("/", include_in_schema=False)
    async def root():
        return FileResponse("static/index.html")

    return app


app = create_app()
