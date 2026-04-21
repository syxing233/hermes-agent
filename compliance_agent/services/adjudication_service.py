from __future__ import annotations

from compliance_agent.models.schemas import AdjudicationResult, Finding, RiskLevel, SkillResult


RISK_WEIGHT = {
    RiskLevel.NONE: 0,
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
}


def adjudicate_results(results: list[SkillResult]) -> AdjudicationResult:
    merged = _dedupe_findings([f for r in results for f in r.findings])

    risk_items = [f for f in merged if f.has_risk]
    pass_items = [f for f in merged if not f.has_risk]

    max_level = RiskLevel.NONE
    for item in risk_items:
        if RISK_WEIGHT[item.risk_level] > RISK_WEIGHT[max_level]:
            max_level = item.risk_level

    total = len(merged)
    score = _risk_score(merged)
    confidence = round(sum(f.confidence for f in merged) / total, 4) if total else 1.0

    return AdjudicationResult(
        risk_score=score,
        max_risk_level=max_level,
        total_findings=total,
        risk_findings=len(risk_items),
        pass_findings=len(pass_items),
        confidence=confidence,
        merged_findings=merged,
    )


def _dedupe_findings(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[Finding] = []
    for finding in findings:
        key = (finding.source_skill.strip(), finding.check_item.strip(), finding.reason.strip())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def _risk_score(findings: list[Finding]) -> float:
    if not findings:
        return 0.0
    score_sum = sum(RISK_WEIGHT[f.risk_level] for f in findings)
    raw = score_sum / (len(findings) * 3)
    return round(raw * 100, 2)
