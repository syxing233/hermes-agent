"""Material-type-specific skills that delegate to MaterialSkillRouter."""

from __future__ import annotations

from compliance_agent.models.schemas import (
    ComplianceRequest,
    Evidence,
    Finding,
    MaterialType,
    RiskLevel,
    SkillResult,
)
from compliance_agent.skills.base import SkillContext
from compliance_agent.skills.helpers import new_finding_id
from compliance_agent.skills.registry import MATERIAL_SKILL_SPECS, MATERIAL_TYPE_TO_SKILL, SKILL_SPECS


def _classify_risk_level(result_text: str) -> tuple[RiskLevel, bool]:
    """Derive risk_level and has_risk from the result text."""
    text = (result_text or "").strip()
    if "不存在风险" in text or "不提出风险" in text or "无风险" in text:
        return RiskLevel.NONE, False
    if "提出风险" in text or "存在风险" in text:
        return RiskLevel.HIGH, True
    return RiskLevel.MEDIUM, True


def _report_to_skill_result(
    skill_name: str,
    report,
) -> SkillResult:
    """Convert a SkillReviewReport into the graph-compatible SkillResult."""
    findings: list[Finding] = []
    for item in report.items:
        risk_level, has_risk = _classify_risk_level(item.result)
        findings.append(
            Finding(
                finding_id=new_finding_id(),
                source_skill=skill_name,
                check_item=item.check_title or "检测项",
                risk_level=risk_level,
                has_risk=has_risk,
                reason=item.reason or item.result or "无",
                evidence=[
                    Evidence(
                        quote=item.source_excerpt or "无",
                        page=1,
                    )
                ],
                suggestion=item.suggestion or None,
                citation=item.basis or None,
                confidence=0.8,
            )
        )

    if not findings:
        if not report.supported:
            findings.append(
                Finding(
                    finding_id=new_finding_id(),
                    source_skill=skill_name,
                    check_item="物料类型不支持",
                    risk_level=RiskLevel.MEDIUM,
                    has_risk=True,
                    reason=report.unsupported_reason or "当前物料类型暂不支持自动检测",
                    evidence=[Evidence(quote="无", page=1)],
                    suggestion="请人工复核",
                    confidence=0.3,
                )
            )

    return SkillResult(
        skill=skill_name,
        findings=findings,
        raw_output=report.raw.answer_markdown if report.raw else "",
    )


class MaterialSkill:
    """A skill that calls MaterialSkillRouter for a specific material type."""

    def __init__(self, name: str, material_type: MaterialType, router):
        self.name = name
        self.material_type = material_type
        self._router = router

    def run(self, ctx: SkillContext) -> SkillResult:
        req = ctx.request.model_copy(
            update={"material_type": self.material_type}
        )
        report = self._router.execute(req, source=self.name)
        return _report_to_skill_result(self.name, report)


def build_material_skills(router) -> dict[str, MaterialSkill]:
    """Build all configured material skills backed by the given router."""
    return {
        spec.skill_name: MaterialSkill(
            name=spec.skill_name,
            material_type=spec.material_type,
            router=router,
        )
        for spec in MATERIAL_SKILL_SPECS
    }
