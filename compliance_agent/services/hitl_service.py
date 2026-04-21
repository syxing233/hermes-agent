from __future__ import annotations

from compliance_agent.config import settings
from compliance_agent.hermes.runtime_config import HitlPolicy
from compliance_agent.models.schemas import AdjudicationResult, ComplianceRequest, HumanReview, RiskLevel


def decide_human_review(
    req: ComplianceRequest,
    result: AdjudicationResult,
    policy: HitlPolicy | None = None,
) -> HumanReview:
    resolved_policy = policy or HitlPolicy(
        confidence_threshold=getattr(settings, "hitl_confidence_threshold", 0.55),
        high_risk_threshold=getattr(settings, "hitl_high_risk_threshold", 1),
    )
    if req.human_review_override is not None:
        return HumanReview(required=req.human_review_override, comments="由请求参数强制指定")

    high_risk_count = sum(1 for finding in result.merged_findings if finding.risk_level == RiskLevel.HIGH)
    low_confidence = result.confidence < resolved_policy.confidence_threshold

    required = high_risk_count >= resolved_policy.high_risk_threshold or low_confidence
    reason = (
        f"自动判定触发人工复核: high_risk_count={high_risk_count}, confidence={result.confidence}"
        if required
        else "自动判定无需人工复核"
    )
    return HumanReview(required=required, comments=reason)
