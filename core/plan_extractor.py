"""
Plan Extractor — LLM call #1.

Converts a natural-language question into a structured Plan, using the
metric catalog and entity vocabulary loaded from Neo4j as the only
allowed slot sources. Output is strict JSON matching the Plan schema
in core.models.

The model is asked for JSON output only (no prose, no markdown). A
single retry with the validation error feedback is performed if the
response fails to parse or violates schema.
"""

import json
from openai import AzureOpenAI
from core.models import Plan, PlanMetric, Threshold, Filter, Ranking, Period
from core.ontology_queries import fetch_metric_catalog, fetch_terms
from config.settings import get_settings
from config.logging_config import get_logger

logger = get_logger(__name__)


SYSTEM_PROMPT = """You translate a user's natural-language analytics question into a strict JSON plan.

You may ONLY use:
- metric IDs from the METRIC CATALOG (start with `m_`)
- column names that appear in some metric's `sliceable_by`
- entity values from the TERM VOCABULARY
- period expressions from the TERM VOCABULARY (category=periods)

Output JSON schema:
{
  "output":   "aggregate" | "list",
  "metrics":  [ { "id": "m_*", "threshold": { "op": ">|>=|<|<=|=|!=", "value": <number> } | null } ],
  "group_by": [ "<column>" ],
  "filters":  [ { "column": "<column>", "op": "=|!=|in|like", "value": <string|number|list> } ],
  "period":   { "expression": "<snowflake predicate fragment with the metric's date_column substituted>" } | null,
  "ranking":  { "by_metric": "m_*", "direction": "ASC|DESC", "limit": <int 1..1000> } | null,
  "confidence": <0..1>,
  "notes":    "<short explanation>"
}

Rules:
1. Pick metrics whose synonyms or example questions clearly match the user's intent.
   For listing questions ("list contracts", "show stations"), choose a metric of kind=list.
   For numeric questions ("how many", "rate", "hours"), choose a metric of kind=metric.
2. `output` must be "list" if any selected metric has kind=list, else "aggregate".
3. Every column referenced in group_by, filters, or ranking.by_metric MUST appear in
   at least one of the selected metrics' sliceable_by lists (or the metrics' alias for ranking).
4. Numeric thresholds like "more than 10%" become threshold on the corresponding metric,
   NOT a filter.
5. "top N by X", "bottom N by X" → set ranking. Otherwise omit.
6. Periods like "last quarter", "YTD" → use the period vocabulary's expression with
   {date_col} replaced by the metric's date_column. If multiple metrics with different
   date_columns are selected, pick the first metric's date_column. If no period is
   mentioned, set period to null.
7. Resolve user terms to canonical values via the TERM VOCABULARY. For station codes,
   uppercase the value (e.g. "msp" → "MSP"). For customer/region/division names use
   the canonical text exactly.
8. Output ONLY the JSON object. No markdown fences, no prose.
9. If the question is ambiguous or cannot be answered with the available metrics,
   set metrics=[], confidence<0.4, and put the reason in notes."""


def _build_user_prompt(question: str) -> str:
    catalog = fetch_metric_catalog()
    terms = fetch_terms()
    return (
        f"METRIC CATALOG ({len(catalog)} metrics):\n"
        f"{json.dumps(catalog, indent=2, default=str)}\n\n"
        f"TERM VOCABULARY:\n"
        f"{json.dumps(terms, indent=2, default=str)}\n\n"
        f"USER QUESTION:\n{question}\n\n"
        f"Return ONLY the JSON plan."
    )


def extract_plan(question: str) -> Plan:
    settings = get_settings()
    client = AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(question)},
    ]

    last_error: str | None = None
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=settings.azure_openai_deployment,
                messages=messages,
                temperature=0.0,
                max_completion_tokens=1024,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or ""
            plan = _parse_plan(raw)
            logger.info(
                "plan_extracted",
                attempt=attempt,
                metrics=[m.id for m in plan.metrics],
                output=plan.output,
                group_by=plan.group_by,
                tokens=response.usage.total_tokens if response.usage else 0,
            )
            return plan

        except Exception as e:
            last_error = str(e)
            logger.warning("plan_extraction_failed", attempt=attempt, error=last_error)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Your previous response could not be parsed: {last_error}. "
                        f"Return ONLY a valid JSON object matching the schema."
                    ),
                }
            )

    raise RuntimeError(f"plan extraction failed after retry: {last_error}")


# ─── Parsing ──────────────────────────────────────────────────────────


def _parse_plan(raw: str) -> Plan:
    """Parse and validate the JSON returned by the LLM into a Plan."""
    raw = raw.strip()
    # tolerate fenced output even though we asked for JSON-only
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    obj = json.loads(raw)

    output = (obj.get("output") or "aggregate").lower()
    if output not in {"aggregate", "list"}:
        output = "aggregate"

    metrics: list[PlanMetric] = []
    for m in obj.get("metrics") or []:
        mid = m.get("id")
        if not mid or not isinstance(mid, str) or not mid.startswith("m_"):
            continue
        thresh = None
        t = m.get("threshold")
        if t and isinstance(t, dict) and "op" in t and "value" in t:
            try:
                thresh = Threshold(op=str(t["op"]), value=float(t["value"]))
            except (TypeError, ValueError):
                thresh = None
        metrics.append(PlanMetric(id=mid, threshold=thresh))

    group_by = [str(g) for g in (obj.get("group_by") or []) if isinstance(g, str)]

    filters: list[Filter] = []
    for f in obj.get("filters") or []:
        col = f.get("column")
        op = f.get("op", "=")
        val = f.get("value")
        if col and op and val is not None:
            filters.append(Filter(column=str(col), op=str(op), value=val))

    period = None
    p = obj.get("period")
    if p and isinstance(p, dict) and p.get("expression"):
        period = Period(expression=str(p["expression"]))

    ranking = None
    r = obj.get("ranking")
    if r and isinstance(r, dict) and r.get("by_metric"):
        try:
            ranking = Ranking(
                by_metric=str(r["by_metric"]),
                direction=str(r.get("direction", "DESC")).upper(),
                limit=int(r.get("limit", 10)),
            )
        except (TypeError, ValueError):
            ranking = None

    confidence = obj.get("confidence")
    try:
        conf_f = float(confidence) if confidence is not None else 1.0
    except (TypeError, ValueError):
        conf_f = 1.0

    return Plan(
        output=output,
        metrics=metrics,
        group_by=group_by,
        filters=filters,
        period=period,
        ranking=ranking,
        confidence=max(0.0, min(1.0, conf_f)),
        notes=str(obj.get("notes") or ""),
    )
