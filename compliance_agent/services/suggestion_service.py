from __future__ import annotations

from compliance_agent.models.schemas import AdjudicationResult, Suggestion


def build_suggestions(adjudication: AdjudicationResult) -> list[Suggestion]:
    suggestions: list[Suggestion] = []

    for finding in adjudication.merged_findings:
        if not finding.has_risk or not finding.suggestion:
            continue
        suggestions.append(
            Suggestion(
                title=f"[{finding.source_skill}] {finding.check_item}",
                detail=finding.suggestion,
                priority=1 if finding.risk_level.value == "高" else 2,
            )
        )

    if not suggestions:
        suggestions.append(Suggestion(title="未发现显著风险", detail="当前检测结果可通过，建议复核发布版本。", priority=3))

    return suggestions
