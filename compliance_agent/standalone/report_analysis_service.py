from __future__ import annotations

import json
from typing import Callable

from compliance_agent.config import settings
from compliance_agent.models.schemas import BatchSkillReviewReport, ReportAnalysis, SkillCheckItem
from compliance_agent.services.external_workflow_client import ExternalWorkflowClient
from compliance_agent.services.material_skill_service import summarize_items


class ReportAnalysisService:
    def __init__(self, client: ExternalWorkflowClient | None = None):
        self.client = client or ExternalWorkflowClient(
            base_url=settings.openai_base_url if settings.openai_api_key else settings.workflow_base_url,
            timeout_seconds=settings.workflow_timeout_seconds,
            max_retries=settings.workflow_max_retries,
        )

    def analyze(self, report: BatchSkillReviewReport) -> ReportAnalysis:
        if not _can_use_model():
            return _build_fallback_analysis(report)

        messages = _build_analysis_messages(report)
        try:
            answer = self.client.run_chat_completions(
                messages=messages,
                api_key=settings.openai_api_key,
                model=settings.model,
                temperature=0.2,
                max_tokens=1200,
            )
        except Exception:
            return _build_fallback_analysis(report)

        text = (answer or "").strip()
        if not text:
            return _build_fallback_analysis(report)

        return ReportAnalysis(
            summary_markdown=text,
            model=settings.model,
            based_on_items=_count_items(report),
            generated_by_model=True,
        )

    def analyze_stream(
        self,
        report: BatchSkillReviewReport,
        chunk_callback: Callable[[str], None] | None = None,
    ) -> ReportAnalysis:
        if not _can_use_model():
            return _emit_fallback_analysis(report, chunk_callback)

        messages = _build_analysis_messages(report)
        chunks: list[str] = []
        try:
            for delta in self.client.stream_chat_completions(
                messages=messages,
                api_key=settings.openai_api_key,
                model=settings.model,
                temperature=0.2,
                max_tokens=1200,
            ):
                if not delta:
                    continue
                chunks.append(delta)
                if chunk_callback is not None:
                    chunk_callback(delta)
        except Exception:
            return _emit_fallback_analysis(report, chunk_callback)

        text = "".join(chunks).strip()
        if not text:
            return _emit_fallback_analysis(report, chunk_callback)

        return ReportAnalysis(
            summary_markdown=text,
            model=settings.model,
            based_on_items=_count_items(report),
            generated_by_model=True,
        )


def _can_use_model() -> bool:
    return bool(settings.enable_llm_report_analysis and settings.openai_api_key)


def _build_analysis_messages(report: BatchSkillReviewReport) -> list[dict[str, str]]:
    payload = _build_analysis_payload(report)
    system_prompt = (
        "你是保险/合同合规报告解读助手。"
        "你的任务是基于结构化检测结果，为客户生成一份简洁、可执行、不能编造的中文总结。"
        "要求："
        "1. 只能基于提供的 findings 总结，不得引入未出现的法规、条款或事实；"
        "2. 优先指出高优先级和重复出现的问题；"
        "3. 用客户能理解的话解释风险，不要只重复检测结果；"
        "4. 输出 Markdown，包含四部分标题：## 总体结论、## 优先处理问题、## 共性问题、## 建议动作；"
        "5. 如果没有风险项，明确说明整体风险较低，并给出轻量建议。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _build_analysis_payload(report: BatchSkillReviewReport) -> dict[str, object]:
    findings: list[dict[str, str]] = []
    for single in report.reports:
        source = single.meta.source or single.meta.input_file or "输入内容"
        material_type = single.meta.material_type or ""
        for item in single.items[:12]:
            findings.append(
                {
                    "source": source,
                    "material_type": material_type,
                    "check_title": item.check_title,
                    "result": item.result,
                    "reason": item.reason,
                    "basis": item.basis,
                    "suggestion": item.suggestion,
                }
            )

    findings.sort(key=lambda item: _risk_sort_key(item.get("result", "")))
    trimmed_findings = findings[:24]

    return {
        "summary": report.summary.model_dump(mode="json"),
        "source_count": report.source_count,
        "material_types": sorted(
            {
                single.meta.material_type
                for single in report.reports
                if single.meta.material_type
            }
        ),
        "findings": trimmed_findings,
    }


def _risk_sort_key(result: str) -> tuple[int, str]:
    text = str(result or "")
    if "高风险" in text:
        return (0, text)
    if "中风险" in text:
        return (1, text)
    if "低风险" in text:
        return (2, text)
    if "提出风险" in text or "存在风险" in text:
        return (3, text)
    return (4, text)


def _build_fallback_analysis(report: BatchSkillReviewReport) -> ReportAnalysis:
    text = _build_fallback_summary_markdown(report)
    return ReportAnalysis(
        summary_markdown=text,
        model="",
        based_on_items=_count_items(report),
        generated_by_model=False,
    )


def _emit_fallback_analysis(
    report: BatchSkillReviewReport,
    chunk_callback: Callable[[str], None] | None,
) -> ReportAnalysis:
    analysis = _build_fallback_analysis(report)
    if chunk_callback is not None and analysis.summary_markdown:
        chunk_callback(analysis.summary_markdown)
    return analysis


def _build_fallback_summary_markdown(report: BatchSkillReviewReport) -> str:
    summary = report.summary
    risk_items = _pick_priority_items(report, risk_only=True, limit=5)
    all_items = _pick_priority_items(report, risk_only=False, limit=3)

    lines = ["## 总体结论", ""]
    if summary.risk_count > 0:
        lines.append(
            f"本次共检测 {summary.total_items} 条，其中风险 {summary.risk_count} 条、通过 {summary.no_risk_count} 条。"
            "建议优先处理会影响宣传合规性、合同效力或客户理解的条目。"
        )
    else:
        lines.append(
            f"本次共检测 {summary.total_items} 条，暂未发现明确风险项。"
            "当前材料整体风险较低，但仍建议在发布或签署前做一次人工复核。"
        )

    lines.extend(["", "## 优先处理问题", ""])
    target_items = risk_items or all_items
    if target_items:
        for index, entry in enumerate(target_items, start=1):
            source = entry["source"]
            item = entry["item"]
            lines.append(
                f"{index}. 【{source}】{item.check_title or '检测项'}："
                f"{item.reason or item.result or '需进一步关注'}"
            )
    else:
        lines.append("1. 当前没有可供提炼的重点问题。")

    lines.extend(["", "## 共性问题", ""])
    pattern_lines = _build_pattern_lines(report)
    if pattern_lines:
        lines.extend(pattern_lines)
    else:
        lines.append("1. 当前结果中未出现明显重复问题，可重点核查措辞一致性和证据留存。")

    lines.extend(["", "## 建议动作", ""])
    action_lines = _build_action_lines(report)
    lines.extend(action_lines or ["1. 结合原文逐条复核检测项，并在最终版本留痕保存。"])
    return "\n".join(lines).strip()


def _pick_priority_items(
    report: BatchSkillReviewReport,
    *,
    risk_only: bool,
    limit: int,
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for single in report.reports:
        source = single.meta.source or single.meta.input_file or "输入内容"
        summary = summarize_items(single.items)
        if risk_only and summary.risk_count <= 0:
            continue
        for item in single.items:
            if risk_only and _risk_sort_key(item.result)[0] >= 4:
                continue
            entries.append({"source": source, "item": item, "risk": _risk_sort_key(item.result)})
    entries.sort(key=lambda entry: entry["risk"])
    return entries[:limit]


def _build_pattern_lines(report: BatchSkillReviewReport) -> list[str]:
    patterns: dict[str, int] = {}
    for single in report.reports:
        for item in single.items:
            text = f"{item.reason} {item.suggestion} {item.check_title}"
            if "绝对化" in text:
                patterns["绝对化或承诺性表述"] = patterns.get("绝对化或承诺性表述", 0) + 1
            if "依据" in text or "法规" in text or "法律" in text:
                patterns["法规依据或条款引用需要核实"] = patterns.get("法规依据或条款引用需要核实", 0) + 1
            if "发票" in text or "税" in text:
                patterns["费用、税费或发票约定需要补充"] = patterns.get("费用、税费或发票约定需要补充", 0) + 1
            if "违约" in text or "解除" in text:
                patterns["违约责任或解除后果需要更明确"] = patterns.get("违约责任或解除后果需要更明确", 0) + 1

    ranked = sorted(patterns.items(), key=lambda item: (-item[1], item[0]))
    return [f"{index}. {label}" for index, (label, _) in enumerate(ranked[:3], start=1)]


def _build_action_lines(report: BatchSkillReviewReport) -> list[str]:
    actions: list[str] = []
    for single in report.reports:
        for item in single.items:
            suggestion = (item.suggestion or "").strip()
            if suggestion and suggestion not in {"无", "-"}:
                actions.append(suggestion)

    deduped: list[str] = []
    seen: set[str] = set()
    for action in actions:
        normalized = " ".join(action.split())
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= 4:
            break

    return [f"{index}. {text}" for index, text in enumerate(deduped, start=1)]


def _count_items(report: BatchSkillReviewReport) -> int:
    total = 0
    for single in report.reports:
        total += len(single.items)
    return total
