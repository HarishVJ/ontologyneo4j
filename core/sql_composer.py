"""
SQL Composer — LLM call #2.

Resolves every metric in the Plan to a MetricSpec (view, expression,
join chain for each requested grouping dimension), then asks the LLM
to emit a single Snowflake SQL statement that honours:

- one CTE per aggregation metric, joined on shared group_by dimensions
- DISTINCT projection for `kind: list` metrics
- thresholds in outer WHERE
- ranking via ORDER BY + LIMIT
- period filter applied within each CTE on the metric's date_column
"""

import json
import re
from openai import AzureOpenAI
from core.models import Plan, MetricSpec
from core.ontology_queries import fetch_metric_catalog, fetch_view_meta, resolve_join_chain
from config.settings import get_settings
from config.logging_config import get_logger

logger = get_logger(__name__)


SYSTEM_PROMPT = """You are a Snowflake SQL composer.

You receive:
- A PLAN (structured JSON describing what to compute)
- A set of METRIC_SPECS — each contains the metric's primary view, alias,
  expression template, sliceable dimensions, and a JOIN_CHAIN per requested
  group_by dimension (the chain is empty if the dimension lives on the
  primary view).

Compose a single Snowflake SQL statement. Rules:

1. For PLAN.output == "aggregate":
   - Build one CTE per metric. Inside each CTE:
       * SELECT the requested group_by dimension columns (resolved via JOIN_CHAIN
         — qualify with the chain's end-view alias if that's where the dimension
         lives).
       * Compute the metric expression with the metric's view alias substituted
         in for `{alias}`.
       * FROM the metric's primary view (fully qualified `<schema>.<view> <alias>`).
       * Apply each JOIN_CHAIN hop as a JOIN on the rendered `on` template
         (substitute `{from_alias}` and `{to_alias}` from the hops).
       * Apply PLAN.filters that target columns this CTE can see.
       * Apply PLAN.period.expression if the metric has a date_column, with
         {date_col} already substituted by the plan extractor.
       * GROUP BY the group_by dimensions.
   - Outer SELECT joins the CTEs INNER JOIN on the shared group_by columns,
     selects the group_by columns and each metric's alias.
   - Apply each metric's threshold (`metric_alias <op> <value>`) in outer WHERE.
   - Apply PLAN.ranking (ORDER BY ranking.by_metric direction, LIMIT n) if present;
     otherwise ORDER BY the first group_by column.

2. For PLAN.output == "list" (single metric, kind=list):
   - SELECT [DISTINCT] the metric's list_columns (or override with PLAN.group_by
     if the user explicitly asked for a narrower projection; otherwise prefer
     list_columns).
   - FROM the primary view, applying any required join chains for filters that
     target columns reachable only via a join.
   - WHERE clause from PLAN.filters; thresholds and ranking do NOT apply to
     list output.
   - ORDER BY metric.default_order_by.
   - DISTINCT iff metric.distinct_on is non-empty.

3. Always fully qualify view names: `<schema>.<view> <alias>`.
4. Never use SELECT *.
5. Never emit semicolons. No markdown fences. No prose. SQL only."""


def _build_metric_spec(metric_id: str, group_by: list[str]) -> MetricSpec | None:
    """Look up a metric in the catalog and resolve its join chains."""
    catalog = {m["id"]: m for m in fetch_metric_catalog()}
    raw = catalog.get(metric_id)
    if not raw:
        logger.warning("metric_not_in_catalog", metric_id=metric_id)
        return None

    view = fetch_view_meta(raw["view"]) if raw.get("view") else None
    if not view:
        logger.warning("metric_view_missing", metric_id=metric_id, view=raw.get("view"))
        return None

    chains = {dim: resolve_join_chain(metric_id, dim) for dim in group_by}

    return MetricSpec(
        id=raw["id"],
        kind=raw.get("kind") or "metric",
        name=raw.get("name") or raw["id"],
        description=raw.get("description") or "",
        view=view,
        expression=raw.get("expression") or "",
        alias=raw.get("alias") or "",
        unit=raw.get("unit") or "",
        polarity=raw.get("polarity") or "",
        list_columns=raw.get("list_columns") or [],
        distinct_on=raw.get("distinct_on") or "",
        default_order_by=raw.get("default_order_by") or [],
        date_column=raw.get("date_column") or "",
        sliceable_by=raw.get("sliceable_by") or [],
        join_chains=chains,
    )


def resolve_metric_specs(plan: Plan) -> list[MetricSpec]:
    """Resolve every metric in the plan; raises if any cannot be resolved."""
    specs: list[MetricSpec] = []
    for pm in plan.metrics:
        spec = _build_metric_spec(pm.id, plan.group_by)
        if not spec:
            raise ValueError(f"metric '{pm.id}' could not be resolved against the ontology")
        specs.append(spec)
    return specs


def _spec_payload(spec: MetricSpec) -> dict:
    """Serialize a MetricSpec into the JSON shape the LLM consumes."""
    return {
        "id": spec.id,
        "kind": spec.kind,
        "name": spec.name,
        "view": {
            "name": spec.view.name,
            "schema": spec.view.schema,
            "alias": spec.view.alias,
            "columns": spec.view.columns,
        },
        "expression_template": spec.expression,
        "alias": spec.alias,
        "list_columns": spec.list_columns,
        "distinct_on": spec.distinct_on,
        "default_order_by": spec.default_order_by,
        "date_column": spec.date_column,
        "sliceable_by": spec.sliceable_by,
        "join_chains": {
            dim: {
                "end_view": ch.end_view,
                "hops": [
                    {
                        "join_id": h.join_id,
                        "on": h.on,
                        "type": h.type,
                        "from_view": h.from_view,
                        "to_view": h.to_view,
                    }
                    for h in ch.hops
                ],
            }
            for dim, ch in spec.join_chains.items()
        },
    }


def compose_sql(plan: Plan, specs: list[MetricSpec]) -> str:
    settings = get_settings()
    client = AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )

    user_prompt = (
        f"PLAN:\n{json.dumps(plan.to_dict(), indent=2, default=str)}\n\n"
        f"METRIC_SPECS:\n{json.dumps([_spec_payload(s) for s in specs], indent=2, default=str)}\n\n"
        f"SCHEMA_PREFIX (already used in METRIC_SPECS[].view.schema): {settings.snowflake_schema_prefix}\n\n"
        f"Compose the Snowflake SQL now."
    )

    response = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
        max_completion_tokens=2048,
    )
    raw = response.choices[0].message.content or ""
    sql = _clean_sql(raw)
    logger.info(
        "sql_composed",
        metrics=[s.id for s in specs],
        sql_length=len(sql),
        tokens=response.usage.total_tokens if response.usage else 0,
    )
    return sql


def _clean_sql(raw: str) -> str:
    """Strip markdown fences and trailing semicolons from the LLM output."""
    raw = raw.strip()
    fence = re.search(r"```(?:sql)?\s*(.*?)\s*```", raw, re.DOTALL | re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    return raw.rstrip(";").rstrip()
