"""
LLM-based SQL generator using Azure OpenAI.
The LLM is constrained — it receives a structured recipe and translates to Snowflake SQL.
It does NOT decide what to compute; the ontology graph has already decided that.
"""

import re
import hashlib
from openai import AzureOpenAI
from core.models import StructuredContext
from config.settings import get_settings
from config.logging_config import get_logger

logger = get_logger(__name__)

# In-process SQL cache: context hash → SQL string
# Eliminates LLM round-trip for repeated identical queries (~1.5-2s saving)
_sql_cache: dict[str, str] = {}

SYSTEM_PROMPT = """You are a Snowflake SQL generator. You receive a structured context describing:
- The KPI to compute
- The exact view(s) to use (fully qualified with schema)
- The columns available
- The filters to apply
- The computation steps
- The output shape (columns, ordering)

RULES:
1. Use ONLY the views and columns provided in the context.
2. Always fully qualify view names: {schema_prefix}.VIEW_NAME
3. Never use SELECT * — always specify columns explicitly.
4. Apply all filters provided in the context as WHERE conditions.
5. Use DISTINCT where appropriate for list queries.
6. Use COUNT(DISTINCT column) for counting queries.
7. Apply ORDER BY as specified in output shape.
8. If grouping is specified, use GROUP BY.
9. Output ONLY the SQL query — no explanations, no markdown fences.
10. Use single quotes for string literals in WHERE clauses.
"""


def _cache_key(context: StructuredContext) -> str:
    """Deterministic cache key from KPI id + sorted filters."""
    raw = f"{context.kpi_id}|{sorted(context.filters)}|{context.grouping}"
    return hashlib.md5(raw.encode()).hexdigest()


def generate_sql(context: StructuredContext) -> str:
    """Generate Snowflake SQL from structured context using Azure OpenAI.
    Cache hit = ~0ms. Cache miss = LLM round-trip (~1.5-2s).
    """
    # Check cache first
    key = _cache_key(context)
    if key in _sql_cache:
        logger.info("sql_cache_hit", kpi=context.kpi_name)
        return _sql_cache[key]

    settings = get_settings()

    client = AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )

    # Build the user prompt from structured context
    user_prompt = _build_user_prompt(context)

    try:
        response = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT.replace("{schema_prefix}", context.schema_prefix),
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_completion_tokens=2048,
        )

        raw_sql = response.choices[0].message.content or ""
        sql = _extract_sql(raw_sql)

        logger.info(
            "sql_generated",
            kpi=context.kpi_name,
            tokens=response.usage.total_tokens if response.usage else 0,
            sql_length=len(sql),
        )
        # Store in cache for subsequent identical requests
        _sql_cache[key] = sql
        return sql

    except Exception as e:
        logger.error("sql_generation_failed", error=str(e), kpi=context.kpi_name)
        raise


def _build_user_prompt(context: StructuredContext) -> str:
    """Build a compact user prompt from structured context."""
    parts = [
        f"KPI: {context.kpi_name}",
        f"Formula: {context.formula}",
        f"Schema prefix: {context.schema_prefix}",
    ]

    # Views and columns
    for view in context.views:
        cols = ", ".join(view["columns"][:30]) if view["columns"] else "all columns in view"
        parts.append(f"View: {view['name']} (alias: {view['alias']})")
        parts.append(f"  Columns: {cols}")

    # Filters
    if context.filters:
        parts.append(f"Filters: {' AND '.join(context.filters)}")

    # Steps
    if context.steps:
        parts.append("Computation steps:")
        for step in context.steps:
            parts.append(f"  - {step}")

    # Output shape
    if context.output_columns:
        parts.append(f"Output columns: {', '.join(context.output_columns)}")

    if context.order_by:
        parts.append(f"Order by: {', '.join(context.order_by)}")

    if context.grouping:
        parts.append(f"Group by: {context.grouping}")

    return "\n".join(parts)


def _extract_sql(raw: str) -> str:
    """Extract SQL from LLM response, handling markdown code fences."""
    # Remove markdown code fences if present
    match = re.search(r"```(?:sql)?\s*(.*?)\s*```", raw, re.DOTALL)
    if match:
        sql = match.group(1).strip()
    else:
        sql = raw.strip()
    # Strip trailing semicolons — Snowflake connector handles single statements
    sql = sql.rstrip(";").rstrip()
    return sql
