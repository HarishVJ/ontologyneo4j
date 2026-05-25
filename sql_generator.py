"""
SQL Generator Module

Responsibility: Send structured context to LLM (Azure OpenAI) and
receive generated Snowflake SQL.

Component: LLM SQL Generator
Owner: LLM (Azure OpenAI)
"""

import os
import re
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """You are a SQL generation assistant.

Generate Snowflake SQL using only the structured ontology context provided.

Rules:
1. Do not invent formulas.
2. Do not invent joins.
3. Do not use tables or columns outside the provided context.
4. Use readable CTEs for complex KPIs.
5. Generate SELECT-only SQL.
6. Do not execute SQL.
7. If required information is missing, return a clarification request.
8. Use the AIRCO_EDW_UAT.ILINKAICHAT schema prefix for all tables.
9. Always use the table aliases provided in the context.
10. Return ONLY the SQL query, no explanation."""


class SQLGenerator:
    """Generates Snowflake SQL from structured ontology context using Azure OpenAI."""

    def __init__(self):
        self.client = AzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
        )
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        self.schema_prefix = "AIRCO_EDW_UAT.ILINKAICHAT"

    def generate(self, structured_context: dict) -> dict:
        """
        Generate SQL from the structured context.

        Returns:
            {"sql": "...", "model": "...", "tokens_used": N}
        """
        if "error" in structured_context:
            return {"error": structured_context["error"], "sql": None}

        # Build user message from structured context
        user_message = self._build_user_message(structured_context)

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.0,
                max_completion_tokens=2000,
            )

            raw_sql = response.choices[0].message.content.strip()
            sql = self._extract_sql(raw_sql)

            return {
                "sql": sql,
                "model": self.deployment,
                "tokens_used": response.usage.total_tokens if response.usage else 0,
            }

        except Exception as e:
            return {"error": str(e), "sql": None}

    def _build_user_message(self, ctx: dict) -> str:
        """Build the user message for the LLM from structured context."""
        kpi = ctx["kpi_context"]
        lines = [
            f"Question: {ctx['question']}",
            f"",
            f"KPI: {kpi['name']}",
            f"Complexity: {kpi['complexity']}",
            f"Formula: {kpi['formula']}",
            f"Schema: {self.schema_prefix}",
            f"",
            f"Views:",
        ]

        for v in kpi["views"]:
            lines.append(f"  - {self.schema_prefix}.{v['name']} AS {v['alias']}")

        lines.append(f"")
        lines.append(f"Joins:")
        for j in kpi["joins"]:
            lines.append(f"  - {j}")

        lines.append(f"")
        lines.append(f"Filters:")
        for f in kpi["filters"]:
            lines.append(f"  - {f}")

        if "period" in kpi:
            lines.append(f"")
            lines.append(f"Period:")
            lines.append(f"  start_date: {kpi['period']['start_date']}")
            lines.append(f"  end_date: {kpi['period']['end_date']}")
            lines.append(f"  days_in_period: {kpi['period']['days_in_period']}")

        if "calculation_steps" in kpi:
            lines.append(f"")
            lines.append(f"Calculation Steps:")
            for step in kpi["calculation_steps"]:
                lines.append(f"  {step}")

        lines.append(f"")
        lines.append(f"Allowed Columns:")
        for col in kpi["allowed_columns"]:
            lines.append(f"  - {col}")

        return "\n".join(lines)

    def _extract_sql(self, raw: str) -> str:
        """Extract SQL from markdown code blocks if present."""
        match = re.search(r"```(?:sql)?\s*\n?(.*?)```", raw, re.DOTALL)
        if match:
            return match.group(1).strip()
        return raw.strip()
