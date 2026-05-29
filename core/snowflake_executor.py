"""
Snowflake query executor using RSA key-pair authentication.
Read-only. Uses a persistent connection pool to eliminate per-request cold-start
latency (~4-6s first connection, ~200ms reuse).
"""

from config.settings import get_settings
from config.logging_config import get_logger

logger = get_logger(__name__)

PREVIEW_LIMIT = 50       # Rows returned in normal API response
MAX_ROWS = 50000         # Hard ceiling for full CSV export
QUERY_TIMEOUT_SECONDS = 10  # Increased: attrition aggregate views need warm-up time

# Persistent connection — created once per process, reused across requests
_conn = None


def _get_private_key_bytes() -> bytes:
    """Parse PEM private key from settings."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend

    settings = get_settings()
    key_str = settings.snowflake_private_key
    key_str = key_str.replace("\\n", "\n").strip('"').strip("'")
    key_bytes = key_str.encode("utf-8")
    passphrase = settings.snowflake_private_key_passphrase
    pwd = passphrase.encode("utf-8") if passphrase else None
    private_key = serialization.load_pem_private_key(
        key_bytes, password=pwd, backend=default_backend()
    )
    return private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def get_connection():
    """Return persistent Snowflake connection, reconnecting if dropped."""
    global _conn
    import snowflake.connector

    if _conn is None or _conn.is_closed():
        settings = get_settings()
        logger.info("snowflake_connecting")
        _conn = snowflake.connector.connect(
            account=settings.snowflake_account,
            user=settings.snowflake_user,
            private_key=_get_private_key_bytes(),
            warehouse=settings.snowflake_warehouse,
            database=settings.snowflake_database,
            schema=settings.snowflake_schema,
            role=settings.snowflake_role,
            network_timeout=QUERY_TIMEOUT_SECONDS,
            # Keep warehouse alive between queries
            session_parameters={"STATEMENT_TIMEOUT_IN_SECONDS": QUERY_TIMEOUT_SECONDS},
        )
        logger.info("snowflake_connected")
    return _conn


def warmup_connection() -> bool:
    """Pre-warm Snowflake connection at app startup to eliminate first-query latency."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        logger.info("snowflake_warmup_complete")
        return True
    except Exception as e:
        logger.warning("snowflake_warmup_failed", error=str(e))
        return False


def close_connection() -> None:
    """Close persistent connection on app shutdown."""
    global _conn
    if _conn and not _conn.is_closed():
        _conn.close()
        _conn = None
        logger.info("snowflake_connection_closed")


def _inject_limit(sql: str, limit: int) -> str:
    """Wrap the SQL in a subquery to enforce a row limit cleanly."""
    return f"SELECT * FROM ({sql}) AS _preview LIMIT {limit}"


def execute_sql(sql: str) -> dict:
    """
    Execute SQL with PREVIEW_LIMIT (50 rows) for the API response.
    If the result hits the limit, sets has_more=True so the UI shows a Download CSV button.
    """
    limited_sql = _inject_limit(sql, PREVIEW_LIMIT + 1)  # fetch 51 to detect overflow
    try:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(limited_sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            has_more = len(rows) > PREVIEW_LIMIT
            if has_more:
                rows = rows[:PREVIEW_LIMIT]
            row_count = len(rows)
            result = {
                "columns": columns,
                "rows": [dict(zip(columns, row)) for row in rows],
                "row_count": row_count,
                "has_more": has_more,
            }
            logger.info("snowflake_query_executed", row_count=row_count,
                        has_more=has_more, columns=len(columns))
            return result
        finally:
            cursor.close()

    except Exception as e:
        logger.error("snowflake_execution_failed", error=str(e))
        global _conn
        _conn = None
        return {"columns": [], "rows": [], "row_count": 0, "has_more": False, "error": str(e)}


def execute_sql_csv(sql: str) -> tuple[list[str], list[tuple]]:
    """
    Execute SQL without a row limit and return (columns, raw_rows) for CSV streaming.
    Used exclusively by the /api/v1/download endpoint.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(MAX_ROWS)
            logger.info("snowflake_csv_export", row_count=len(rows), columns=len(columns))
            return columns, rows
        finally:
            cursor.close()

    except Exception as e:
        logger.error("snowflake_csv_export_failed", error=str(e))
        global _conn
        _conn = None
        raise
