from core.models import (
    ClarificationRequest,
    ExtractionResult,
    KPIRecipe,
    RequirementCheckResult,
)


def check_requirements(extraction: ExtractionResult, recipe: KPIRecipe) -> RequirementCheckResult:
    for category, rule in recipe.dimension_rules.items():
        if not isinstance(rule, dict):
            continue
        if rule.get("support_type") != "unsupported":
            continue
        requested = _category_requested(extraction, category)
        if requested:
            reason = rule.get("reason") or f"{recipe.name} does not support {category}."
            return RequirementCheckResult(status="unsupported", unsupported_reason=reason)

    for field, requirement in recipe.required_context.items():
        if not isinstance(requirement, dict) or not requirement.get("required", False):
            continue
        if field == "period" and not extraction.detected_period:
            return RequirementCheckResult(
                status="clarification",
                clarification=ClarificationRequest(
                    required_field=field,
                    question=requirement.get("clarification_prompt", "Which period should I use?"),
                    options=requirement.get("options", []),
                    reason="A period is required for this KPI.",
                ),
            )
        one_of = requirement.get("one_of", [])
        if one_of and not any(_category_requested(extraction, category) for category in one_of):
            return RequirementCheckResult(
                status="clarification",
                clarification=ClarificationRequest(
                    required_field=field,
                    question=requirement.get("clarification_prompt", "Please provide the missing context."),
                    options=one_of,
                    reason=f"One of these inputs is required: {', '.join(one_of)}.",
                ),
            )

    return RequirementCheckResult(status="ok")


def _category_requested(extraction: ExtractionResult, category: str) -> bool:
    if any(term.category == category for term in extraction.detected_terms.values()):
        return True
    return category in extraction.detected_grouping
