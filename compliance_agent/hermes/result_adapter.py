from __future__ import annotations

from typing import Any

from compliance_agent.hermes.progress_bridge import HermesProgressBridge
from compliance_agent.hermes.session_policy import (
    compact_summary,
    summarize_status_trace,
    trim_text,
)
from compliance_agent.models.schemas import (
    BatchSkillReviewReport,
    SkillCheckItem,
    SkillReviewReport,
)


def adapt_review_result(
    report: BatchSkillReviewReport,
    *,
    artifact_path: str | None,
    progress: HermesProgressBridge | None = None,
) -> dict[str, Any]:
    top_items = (
        progress.top_items()
        if progress and progress.top_items()
        else _extract_top_items(report)
    )
    status_trace_summary = (
        progress.status_trace_summary()
        if progress and progress.status_events
        else summarize_status_trace(report.status_trace)
    )

    compact: dict[str, Any] = {
        "success": True,
        "review_id": report.task_id,
        "material_type": _resolve_material_type(report),
        "material_classification": _resolve_classification_info(report),
        "file_types": _resolve_file_types(report),
        "source_count": report.source_count,
        "summary": compact_summary(report.summary),
        "top_items": top_items,
        "status_trace_summary": status_trace_summary,
        "artifact_path": artifact_path,
    }

    if report.analysis and report.analysis.summary_markdown.strip():
        compact["report_summary"] = trim_text(report.analysis.summary_markdown)
        compact["analysis_generated_by_model"] = bool(
            report.analysis.generated_by_model
        )

    return compact


def adapt_artifact_payload(
    payload: dict[str, Any], *, include_full_report: bool = False
) -> dict[str, Any]:
    result = {
        "success": True,
        "review_id": payload.get("review_id"),
        "summary": payload.get("summary") or {},
        "status_trace_summary": payload.get("status_trace_summary") or [],
        "artifact_path": payload.get("artifact_path") or payload.get("json_path"),
        "compact_result": payload.get("compact_result") or {},
    }
    if include_full_report:
        result["full_report"] = payload.get("report")
    return result


def _resolve_material_type(report: BatchSkillReviewReport) -> str:
    material_types = {
        single.meta.material_type
        for single in report.reports
        if single.meta and single.meta.material_type
    }
    if len(material_types) == 1:
        return next(iter(material_types))
    if not material_types:
        return "未识别"
    return "mixed"


def _resolve_classification_info(report: BatchSkillReviewReport) -> dict[str, str] | None:
    classifications = [
        single.material_classification
        for single in report.reports
        if single.material_classification is not None
    ]
    if not classifications:
        return None
    return classifications[0].model_dump()


def _resolve_file_types(report: BatchSkillReviewReport) -> list[str]:
    file_types = []
    for single in report.reports:
        input_file = single.meta.input_file or ""
        if input_file:
            suffix = input_file.rsplit(".", 1)[-1].lower() if "." in input_file else ""
            file_type = _infer_file_type(suffix)
            label = _FILE_TYPE_LABELS.get(file_type, file_type)
            if suffix:
                label = f"{label}(.{suffix})"
            if label not in file_types:
                file_types.append(label)
    return file_types or ["unknown"]


def _infer_file_type(suffix: str) -> str:
    _TYPE_MAP = {
        "pdf": "pdf",
        "docx": "docx",
        "doc": "doc",
        "xlsx": "xlsx",
        "xlsm": "xlsx",
        "zip": "zip",
        "png": "image",
        "jpg": "image",
        "jpeg": "image",
        "bmp": "image",
        "gif": "image",
        "webp": "image",
        "tif": "image",
        "tiff": "image",
        "txt": "text",
        "md": "text",
        "csv": "text",
        "json": "text",
        "yaml": "text",
        "yml": "text",
        "xml": "text",
        "html": "text",
        "htm": "text",
        "log": "text",
    }
    return _TYPE_MAP.get(suffix, "document")


_FILE_TYPE_LABELS = {
    "pdf": "PDF文档",
    "docx": "Word文档",
    "doc": "Word文档",
    "xlsx": "Excel表格",
    "zip": "压缩包",
    "image": "图片",
    "text": "文本文件",
    "document": "文档",
}


def _extract_top_items(report: BatchSkillReviewReport) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for single in report.reports:
        source = single.meta.source or single.meta.input_file or "输入内容"
        material_type = single.meta.material_type or ""
        for item in single.items:
            items.append(
                _skill_item_to_dict(source=source, material_type=material_type, item=item)
            )
    return items


def _skill_item_to_dict(
    *, source: str, material_type: str, item: SkillCheckItem
) -> dict[str, str]:
    return {
        "source": source,
        "material_type": material_type,
        "check_title": (item.check_title or "检测项").strip(),
        "result": (item.result or "").strip(),
        "reason": (item.reason or "").strip(),
        "basis": (item.basis or "").strip(),
        "suggestion": (item.suggestion or "").strip(),
    }


