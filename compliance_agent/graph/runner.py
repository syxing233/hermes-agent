from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from compliance_agent.config import settings
from compliance_agent.models.schemas import (
    ComplianceRequest,
    MaterialType,
    SkillCheckItem,
    SkillMeta,
    SkillReviewReport,
    StatusEvent,
)
from compliance_agent.skills.registry import (
    SUPPORTED_MATERIAL_TYPES,
    SUPPORTED_MATERIAL_TYPE_OPTIONS,
    default_query_for_material_type,
)
from compliance_agent.services import MaterialSkillRouter


class ComplianceWorkflow:
    def __init__(
        self,
        router: MaterialSkillRouter | None = None,
        stream_report_items_enabled: bool | None = None,
    ):
        self.router = router or MaterialSkillRouter()
        if stream_report_items_enabled is None:
            stream_report_items_enabled = bool(getattr(settings, "enable_streaming_report_items", True))
        self.stream_report_items_enabled = bool(stream_report_items_enabled)

    def run(
        self,
        req: ComplianceRequest,
        status_callback: Callable[[StatusEvent], None] | None = None,
        item_callback: Callable[[SkillMeta, SkillCheckItem], None] | None = None,
    ) -> SkillReviewReport:
        task_id = f"task_{uuid4().hex[:10]}"
        status_trace: list[StatusEvent] = []

        self._emit(
            status_trace,
            status_callback,
            stage="任务接入层",
            detail=f"request accepted, material_type={req.material_type.value}",
            operation="analyzing",
        )

        source_name = _resolve_source_name(req)
        exec_req = req.model_copy(
            update={"query": req.query or _default_query(req.material_type)}
        )

        if exec_req.material_type not in SUPPORTED_MATERIAL_TYPES:
            self._emit(
                status_trace,
                status_callback,
                stage="物料路由层",
                detail=(
                    f"material_type must be one of: {SUPPORTED_MATERIAL_TYPE_OPTIONS}, "
                    f"got={exec_req.material_type.value}"
                ),
                operation="checking",
            )

        self._emit(
            status_trace,
            status_callback,
            stage="物料路由层",
            detail=f"source={source_name}, material_type={exec_req.material_type.value}",
            operation="checking",
        )

        if item_callback is not None and self.stream_report_items_enabled:
            report = self.router.execute_stream(
                exec_req,
                source=source_name,
                task_id=task_id,
                item_callback=item_callback,
            )
        else:
            report = self.router.execute(exec_req, source=source_name, task_id=task_id)

        final_event = StatusEvent(
            at=datetime.utcnow(),
            stage="最终报告输出",
            detail=f"supported={report.supported}, items={len(report.items)}",
            operation="reporting",
        )
        status_trace.extend(report.status_trace)
        status_trace.append(final_event)
        if status_callback:
            try:
                status_callback(final_event)
            except Exception:
                pass

        return report.model_copy(update={"status_trace": status_trace})

    def _emit(
        self,
        status_trace: list[StatusEvent],
        callback: Callable[[StatusEvent], None] | None,
        *,
        stage: str,
        detail: str,
        operation: str,
    ) -> None:
        event = StatusEvent(
            at=datetime.utcnow(),
            stage=stage,
            detail=detail,
            operation=operation,
        )
        status_trace.append(event)
        if callback:
            try:
                callback(event)
            except Exception:
                return


def _resolve_source_name(req: ComplianceRequest) -> str:
    if req.extra and isinstance(req.extra.get("source_name"), str) and req.extra.get("source_name"):
        return str(req.extra["source_name"])
    if req.input_file and req.input_file.local_path:
        return Path(req.input_file.local_path).name
    if req.input_file and req.input_file.upload_file_id:
        return req.input_file.upload_file_id
    return "inline_text_1"


def _default_query(material_type: MaterialType) -> str:
    return default_query_for_material_type(material_type)
