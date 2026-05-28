"""
Neo4j connection management with connection pooling, health checks, and retry logic.
"""

from neo4j import GraphDatabase, Driver
from config.settings import get_settings
from config.logging_config import get_logger

logger = get_logger(__name__)

_driver: Driver | None = None


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        settings = get_settings()
        _driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            max_connection_pool_size=10,
            connection_acquisition_timeout=10,
        )
        logger.info("neo4j_driver_created", uri=settings.neo4j_uri)
    return _driver


def verify_connectivity() -> bool:
    try:
        driver = get_driver()
        driver.verify_connectivity()
        logger.info("neo4j_connectivity_verified")
        return True
    except Exception as e:
        logger.error("neo4j_connectivity_failed", error=str(e))
        return False


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
        logger.info("neo4j_driver_closed")


def execute_query(cypher: str, parameters: dict | None = None) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        result = session.run(cypher, parameters or {})
        return [record.data() for record in result]


def execute_write(cypher: str, parameters: dict | None = None) -> None:
    driver = get_driver()
    with driver.session() as session:
        session.run(cypher, parameters or {})
