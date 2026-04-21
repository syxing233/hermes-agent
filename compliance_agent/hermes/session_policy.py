from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable

from compliance_agent.models.schemas import StatusEvent

MAX_TOP_ITEMS = None
MAX_REPORT_SUMMARY_CHARS = 1200
MAX_STATUS_STAGES = 8

_STAGE_ALIASES = {
    "任务接入层": "输入编排",
    "输入编排层": "输入编排",
    "文档理解层": "输入编排",
    "结构化处理层": "输入编排",
    "文档质量门禁": "输入编排",
    "物料自动分类": "自动分类",
    "规划层": "物料路由",
    "物料路由层": "物料路由",
    "规则与证据服务": "物料路由",
    "Skill执行层": "技能/工作流执行",
    "最终报告输出": "最终报告输出",
}


def should_store_review_in_memory() -> bool:
    return False


def trim_text(value: str | None, max_chars: int = MAX_REPORT_SUMMARY_CHARS) -> str:
    text = (value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def compact_summary(summary: Any) -> dict[str, Any]:
    if summary is None:
        return {}
    if hasattr(summary, "model_dump"):
        payload = summary.model_dump(mode="json")
    elif isinstance(summary, dict):
        payload = dict(summary)
    else:
        payload = {"value": summary}

    ordered_keys = (
        "risk_count",
        "no_risk_count",
        "total_items",
        "supported_count",
        "unsupported_count",
    )
    return {key: payload.get(key) for key in ordered_keys if key in payload}


def summarize_status_trace(events: Iterable[StatusEvent]) -> list[dict[str, Any]]:
    grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for event in events:
        raw_stage = str(getattr(event, "stage", "") or "").strip() or "未命名阶段"
        stage = _STAGE_ALIASES.get(raw_stage, raw_stage)
        bucket = grouped.setdefault(stage, {"stage": stage, "count": 0, "detail": "", "operation": ""})
        bucket["count"] += 1
        bucket["detail"] = trim_text(str(getattr(event, "detail", "") or ""), 240)
        bucket["operation"] = str(getattr(event, "operation", "") or "")

    return list(grouped.values())[:MAX_STATUS_STAGES]


def compact_context_payload(result: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "success",
        "review_id",
        "material_type",
        "source_count",
        "summary",
        "top_items",
        "status_trace_summary",
        "artifact_path",
        "report_summary",
    )
    return {key: result.get(key) for key in keys if key in result}
