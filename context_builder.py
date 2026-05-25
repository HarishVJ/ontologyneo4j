"""
Structured Context Builder Module

Responsibility: Transform Neo4j ontology output into a compact,
structured context object suitable for the LLM SQL Generator.

Component: Structured Context Builder
Owner: Python Backend Service
"""

from typing import Optional


def build_context(
    question: str,
    neo4j_result: dict,
    view_aliases: dict,
    period: Optional[dict] = None,
) -> dict:
    """
    Build the structured context object sent to the LLM.

    Transforms Neo4j ontology lookup result into the format:
    {
        "task": "Generate SQL for KPI question",
        "question": "...",
        "kpi_context": { name, complexity, formula, views, joins, filters, ... }
    }
    """
    if "error" in neo4j_result:
        return {"error": neo4j_result["error"]}

    # Build views list with aliases
    views = []
    for view_name in neo4j_result["required_views"]:
        alias = view_aliases.get(view_name, view_name[0].lower())
        views.append({"name": view_name, "alias": alias})

    # Build joins list (just the conditions)
    joins = [jp["condition"] for jp in neo4j_result.get("join_paths", [])]

    # Build filters list as readable strings
    filters = []
    for f in neo4j_result.get("filters", []):
        filters.append(f"{f['column']} {f['operator']} '{f['value']}'")

    # Build calculation steps (for complex KPIs)
    calculation_steps = []
    if "steps" in neo4j_result:
        for step in neo4j_result["steps"]:
            logic = step["logic"]
            # Substitute period dates if available
            if period:
                logic = logic.replace("start_date", f"'{period['start_date']}'")
                logic = logic.replace("end_date", f"'{period['end_date']}'")
            calculation_steps.append(f"{step['name']}: {logic}")

        # Add final formula step
        if period:
            formula = neo4j_result["formula"].replace(
                "days_in_period", str(period["days_in_period"])
            )
            calculation_steps.append(f"Final Formula: {formula}")
        else:
            calculation_steps.append(f"Final Formula: {neo4j_result['formula']}")

    # Determine task description based on complexity
    complexity = neo4j_result.get("complexity", "simple")
    if complexity == "complex":
        task = "Generate Snowflake SQL for a complex KPI"
    else:
        task = "Generate SQL for KPI question"

    # Assemble the structured context
    kpi_context = {
        "name": neo4j_result["kpi"],
        "complexity": complexity,
        "formula": neo4j_result["formula"],
        "views": views,
        "joins": joins,
        "filters": filters,
        "allowed_columns": neo4j_result.get("allowed_columns", []),
    }

    if period:
        kpi_context["period"] = period

    if calculation_steps:
        kpi_context["calculation_steps"] = calculation_steps

    return {
        "task": task,
        "question": question,
        "kpi_context": kpi_context,
    }
