from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from compliance_agent.config import settings
from compliance_agent.hermes.runtime_config import HitlPolicy, ParsingPolicy
from compliance_agent.models.schemas import (
    ComplianceRequest,
    DetectReport,
    DocumentQuality,
    Evidence,
    ExecutionPlan,
    Finding,
    RiskLevel,
    SkillResult,
    StatusEvent,
)
from compliance_agent.models.state import WorkflowState
from compliance_agent.services import (
    adjudicate_results,
    blocks_from_text,
    build_chunks,
    build_rules_context,
    build_suggestions,
    decide_human_review,
    parse_document_with_quality,
)
from compliance_agent.skills.base import SkillContext
from compliance_agent.skills.helpers import new_finding_id
from compliance_agent.skills.material_skill import (
    MATERIAL_TYPE_TO_SKILL,
    MaterialSkill,
)
from compliance_agent.skills.registry import SUPPORTED_MATERIAL_TYPE_OPTIONS


def _new_status_event(stage: str, detail: str, operation: str) -> StatusEvent:
    return StatusEvent(
        at=datetime.utcnow(),
        stage=stage,
        detail=detail,
        operation=operation,
    )


def _emit_status(state: WorkflowState, event: StatusEvent) -> None:
    callback = state.get("status_callback")
    if callback is None:
        return
    try:
        callback(event)
    except Exception:
        return


def intake_node(state: WorkflowState) -> dict:
    req = state["request"]
    task_id = state.get("task_id") or f"task_{uuid4().hex[:10]}"
    event = _new_status_event(
        stage="任务接入层",
        detail=f"request accepted, material_type={req.material_type.value}",
        operation="analyzing",
    )
    _emit_status(state, event)

    return {
        "task_id": task_id,
        "status_trace": [event],
    }


def document_understanding_node(state: WorkflowState) -> dict:
    req = state["request"]
    prefetched = _load_prefetched_document(req)
    if prefetched is None:
        raw_text, blocks, parse_quality = parse_document_with_quality(req)
    else:
        raw_text, blocks, parse_quality = prefetched
    detail = (
        f"blocks={len(blocks)}, parser={parse_quality.parser}, "
        f"confidence={parse_quality.parse_confidence}, warnings={len(parse_quality.warnings)}"
    )
    if parse_quality.warnings:
        detail += f", first_warning={parse_quality.warnings[0]}"
    event = _new_status_event(stage="文档理解层", detail=detail, operation="analyzing")
    _emit_status(state, event)

    return {
        "raw_text": raw_text,
        "blocks": blocks,
        "parse_quality": parse_quality,
        "status_trace": [event],
    }


def structuring_node(state: WorkflowState) -> dict:
    blocks = state.get("blocks", [])
    chunks = build_chunks(blocks)
    event = _new_status_event(stage="结构化处理层", detail=f"chunks={len(chunks)}", operation="analyzing")
    _emit_status(state, event)

    return {
        "chunks": chunks,
        "status_trace": [event],
    }


def parse_quality_gate_node(state: WorkflowState) -> dict:
    quality = state.get("parse_quality")
    chunks = state.get("chunks", [])
    parsing_policy = state.get("parsing_policy") or ParsingPolicy(
        min_confidence=getattr(settings, "parse_min_confidence", 0.45),
        min_chars=getattr(settings, "parse_min_chars", 80),
    )

    if quality is None:
        quality = DocumentQuality(
            parse_source="unknown",
            parser="unknown",
            parse_confidence=0.0,
            warnings=["未生成 parse_quality，文档理解可能异常"],
        )

    warnings = list(quality.warnings)
    quality.chunk_count = len(chunks)

    if quality.parse_source == "upload_file_id":
        warnings = [w for w in warnings if "upload_file_id" not in w]

    if quality.parse_source != "upload_file_id":
        if quality.parse_confidence < parsing_policy.min_confidence:
            warnings.append(
                f"解析置信度较低({quality.parse_confidence} < {parsing_policy.min_confidence})"
            )
        if quality.char_count < parsing_policy.min_chars:
            warnings.append(f"解析文本过短({quality.char_count} < {parsing_policy.min_chars})")

    if quality.chunk_count == 0 and quality.parse_source != "upload_file_id":
        warnings.append("未生成可用 chunk，建议人工复核原始文件")

    quality.warnings = list(dict.fromkeys(warnings))
    quality.needs_review = bool(quality.warnings)

    event = _new_status_event(
        stage="文档质量门禁",
        detail=_build_quality_gate_detail(quality),
        operation="analyzing",
    )
    _emit_status(state, event)

    payload: dict = {
        "parse_quality": quality,
        "quality_needs_review": quality.needs_review,
        "status_trace": [event],
    }

    if quality.needs_review:
        payload["errors"] = ["document_quality_warning: " + " | ".join(quality.warnings)]

    return payload


def planning_node(state: WorkflowState) -> dict:
    """Select the matching material skill for the request."""
    req: ComplianceRequest = state["request"]
    material_type = req.material_type
    skill_name = MATERIAL_TYPE_TO_SKILL.get(material_type)

    selected = [skill_name] if skill_name else []
    plan = ExecutionPlan(
        labels=[material_type.value],
        selected_skills=selected,
        parallel=False,
        notes="按物料类型选择对应的外部工作流 Skill",
    )

    event = _new_status_event(
        stage="规划层",
        detail=f"material_type={material_type.value}, skill={skill_name or 'none'}",
        operation="analyzing",
    )
    _emit_status(state, event)

    payload: dict = {
        "plan": plan,
        "status_trace": [event],
    }

    if not selected:
        payload["errors"] = [f"No skill configured for material_type={material_type.value}"]

    return payload


def rules_evidence_node(state: WorkflowState) -> dict:
    req = state["request"]
    context = build_rules_context(req)
    event = _new_status_event(
        stage="规则与证据服务",
        detail=f"citations={len(context.get('citations', []))}",
        operation="analyzing",
    )
    _emit_status(state, event)

    return {
        "rules_context": context,
        "status_trace": [event],
    }


def make_skill_execution_node(skills: dict[str, MaterialSkill]):
    """Create a skill execution node that dispatches to MaterialSkill."""

    def skill_execution_node(state: WorkflowState) -> dict:
        req = state["request"]
        chunks = state.get("chunks", [])
        rules_context = state.get("rules_context", {})
        plan = state.get("plan")
        selected = plan.selected_skills if plan else []

        if not selected:
            finding = Finding(
                finding_id=new_finding_id(),
                source_skill="system.no_skill",
                check_item="物料类型匹配",
                risk_level=RiskLevel.MEDIUM,
                has_risk=True,
                reason=f"当前物料类型 {req.material_type.value} 没有匹配的检测 Skill",
                evidence=[Evidence(quote="无", page=1)],
                suggestion=f"请确认物料类型为 {SUPPORTED_MATERIAL_TYPE_OPTIONS} 之一",
                confidence=0.3,
            )
            event = _new_status_event(
                stage="Skill执行层",
                detail="no_matching_skill",
                operation="checking",
            )
            _emit_status(state, event)
            return {
                "skill_results": [SkillResult(skill="system.no_skill", findings=[finding])],
                "status_trace": [event],
            }

        skill_name = selected[0]
        skill = skills.get(skill_name)

        if skill is None:
            finding = Finding(
                finding_id=new_finding_id(),
                source_skill=f"system.missing.{skill_name}",
                check_item="Skill 加载",
                risk_level=RiskLevel.MEDIUM,
                has_risk=True,
                reason=f"Skill '{skill_name}' 未注册",
                evidence=[Evidence(quote="无", page=1)],
                suggestion="请检查 Skill 配置",
                confidence=0.3,
            )
            event = _new_status_event(
                stage="Skill执行层",
                detail=f"skill_not_found={skill_name}",
                operation="checking",
            )
            _emit_status(state, event)
            return {
                "skill_results": [SkillResult(skill=skill_name, findings=[finding])],
                "status_trace": [event],
            }

        ctx = SkillContext(
            request=req,
            chunks=chunks,
            rules_context=rules_context,
            detector_results={},
        )

        try:
            result = skill.run(ctx)
            detail = f"skill={skill_name}, findings={len(result.findings)}"
        except Exception as exc:
            finding = Finding(
                finding_id=new_finding_id(),
                source_skill=skill_name,
                check_item="Skill 执行异常",
                risk_level=RiskLevel.MEDIUM,
                has_risk=True,
                reason=f"Skill 执行失败: {exc}",
                evidence=[Evidence(quote="无", page=1)],
                suggestion="请检查外部工作流 API 是否可达",
                confidence=0.2,
            )
            result = SkillResult(skill=skill_name, findings=[finding])
            detail = f"skill={skill_name}, error={exc.__class__.__name__}"

        event = _new_status_event(
            stage="Skill执行层",
            detail=detail,
            operation="model_calling",
        )
        _emit_status(state, event)

        return {
            "skill_results": [result],
            "status_trace": [event],
        }

    return skill_execution_node


def adjudication_node(state: WorkflowState) -> dict:
    results = state.get("skill_results", [])
    adjudication = adjudicate_results(results)
    event = _new_status_event(
        stage="裁决层",
        detail=(
            f"risk_findings={adjudication.risk_findings}, "
            f"max_level={adjudication.max_risk_level.value}, "
            f"confidence={adjudication.confidence}"
        ),
        operation="checking",
    )
    _emit_status(state, event)

    return {
        "adjudication": adjudication,
        "status_trace": [event],
    }


def hitl_decision_node(state: WorkflowState) -> dict:
    req = state["request"]
    adjudication = state["adjudication"]
    hitl_policy = state.get("hitl_policy") or HitlPolicy(
        confidence_threshold=getattr(settings, "hitl_confidence_threshold", 0.55),
        high_risk_threshold=getattr(settings, "hitl_high_risk_threshold", 1),
    )
    human_review = decide_human_review(req, adjudication, policy=hitl_policy)
    quality_needs_review = state.get("quality_needs_review", False)

    if quality_needs_review:
        human_review.required = True
        review_reason = "文档质量门禁触发人工复核"
        if human_review.comments:
            human_review.comments = f"{human_review.comments}; {review_reason}"
        else:
            human_review.comments = review_reason

    event = _new_status_event(
        stage="人工复核判断",
        detail=human_review.comments or "",
        operation="checking",
    )
    _emit_status(state, event)

    return {
        "needs_human_review": human_review.required,
        "human_review": human_review,
        "status_trace": [event],
    }


def human_review_node(state: WorkflowState) -> dict:
    review = state["human_review"]
    req = state["request"]

    reviewer = req.extra.get("reviewer") if req.extra else None
    review.reviewer = reviewer or "pending_reviewer"

    if not review.comments:
        review.comments = "等待人工复核意见回写"

    event = _new_status_event(
        stage="人工审核工作台",
        detail=f"reviewer={review.reviewer}",
        operation="checking",
    )
    _emit_status(state, event)

    return {
        "human_review": review,
        "status_trace": [event],
    }


def suggestion_node(state: WorkflowState) -> dict:
    adjudication = state["adjudication"]
    suggestions = build_suggestions(adjudication)
    event = _new_status_event(
        stage="修改建议生成",
        detail=f"suggestions={len(suggestions)}",
        operation="checking",
    )
    _emit_status(state, event)

    return {
        "suggestions": suggestions,
        "status_trace": [event],
    }


def report_node(state: WorkflowState) -> dict:
    req = state["request"]
    adjudication = state["adjudication"]
    suggestions = state.get("suggestions", [])

    summary = (
        f"共检测{adjudication.total_findings}项，"
        f"风险{adjudication.risk_findings}项，"
        f"通过{adjudication.pass_findings}项。"
    )

    final_event = _new_status_event(
        stage="最终报告输出",
        detail=f"risk_level={adjudication.max_risk_level.value}",
        operation="reporting",
    )
    _emit_status(state, final_event)

    report = DetectReport(
        task_id=state["task_id"],
        material_type=req.material_type,
        summary=summary,
        risk_level=adjudication.max_risk_level,
        adjudication=adjudication,
        suggestions=suggestions,
        findings=adjudication.merged_findings,
        status_trace=state.get("status_trace", []) + [final_event],
    )

    return {
        "final_report": report,
        "status_trace": [final_event],
    }


def route_hitl(state: WorkflowState) -> str:
    return "human_review" if state.get("needs_human_review") else "skip"


def _build_quality_gate_detail(quality: DocumentQuality) -> str:
    detail = (
        f"needs_review={quality.needs_review}, parser={quality.parser}, "
        f"warnings={len(quality.warnings)}"
    )
    if quality.warnings:
        detail += f", first_warning={quality.warnings[0]}"
    return detail


def _load_prefetched_document(req: ComplianceRequest) -> tuple[str, list, DocumentQuality] | None:
    extra = getattr(req, "extra", None)
    if not isinstance(extra, dict):
        return None

    cached = extra.get("prefetched_document")
    if not isinstance(cached, dict):
        return None

    raw_text = cached.get("raw_text")
    if not isinstance(raw_text, str):
        return None

    parse_quality = _load_prefetched_quality(cached.get("parse_quality"))
    blocks = blocks_from_text(raw_text)
    parse_quality.char_count = len(raw_text)
    parse_quality.block_count = len(blocks)
    return raw_text, blocks, parse_quality


def _load_prefetched_quality(payload: object) -> DocumentQuality:
    if isinstance(payload, dict):
        try:
            return DocumentQuality.model_validate(payload)
        except Exception:
            pass
    return DocumentQuality(
        parse_source="local_path",
        parser="prefetched",
        parse_confidence=0.7,
        warnings=["prefetched_parse_quality_invalid"],
    )
