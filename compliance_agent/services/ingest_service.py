from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import inspect
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

from compliance_agent.models.schemas import (
    BatchSkillReviewReport,
    BatchSkillSummary,
    ComplianceRequest,
    MaterialClassificationInfo,
    MaterialType,
    SkillCheckItem,
    SkillMeta,
    SkillReviewReport,
    StatusEvent,
    UploadFile,
)
from compliance_agent.services.auto_classification_service import (
    AutoClassification,
    MaterialClassificationService,
)

if TYPE_CHECKING:
    from compliance_agent.graph.runner import ComplianceWorkflow


@dataclass(frozen=True)
class IngestSource:
    source_name: str
    source_type: str
    local_path: str | None = None
    upload_file_id: str | None = None
    input_text: str | None = None


class IngestReviewService:
    def __init__(
        self,
        workflow: ComplianceWorkflow | None = None,
        classifier: MaterialClassificationService | None = None,
    ):
        if workflow is None:
            from compliance_agent.graph.runner import (
                ComplianceWorkflow as _ComplianceWorkflow,
            )

            workflow = _ComplianceWorkflow()
        self.workflow = workflow
        self.classifier = classifier or MaterialClassificationService()
        workflow_params = inspect.signature(self.workflow.run).parameters
        self._workflow_accepts_status_callback = "status_callback" in workflow_params
        self._workflow_accepts_item_callback = "item_callback" in workflow_params

    def review_sources(
        self,
        sources: list[IngestSource],
        material_type: MaterialType | None = None,
        hint_material_type: MaterialType | None = None,
        user: str = "anonymous",
        context_text: str | None = None,
        status_callback: Callable[[StatusEvent], None] | None = None,
        item_callback: Callable[[SkillMeta, SkillCheckItem], None] | None = None,
    ) -> BatchSkillReviewReport:
        if not sources:
            raise ValueError("At least one source is required")

        normalized_context_text = (context_text or "").strip()
        trace: list[StatusEvent] = []
        reports: list[SkillReviewReport] = []
        total = len(sources)

        for idx, source in enumerate(sources, start=1):
            start_event = StatusEvent(
                at=datetime.utcnow(),
                stage="输入编排层",
                detail=f"start_source={idx}/{total}, source={source.source_name}",
                operation="analyzing",
            )
            _emit_status(status_callback, start_event)
            trace.append(start_event)

            # Auto-classify if material_type not given
            resolved_type = material_type
            classification_result: AutoClassification | None = None
            if resolved_type is None:
                classification_result, classify_event = self._classify_source(
                    source=source,
                    user=user,
                    hint_material_type=hint_material_type,
                )
                resolved_type = classification_result.material_type
                _emit_status(status_callback, classify_event)
                trace.append(classify_event)

            req = _build_request(
                source=source,
                user=user,
                material_type=resolved_type,
                classification=classification_result,
                context_text=normalized_context_text,
            )

            classification_info = None
            if classification_result:
                classification_info = MaterialClassificationInfo(
                    material_type=classification_result.material_type.value,
                    source=classification_result.source,
                )
            elif material_type is not None:
                classification_info = MaterialClassificationInfo(
                    material_type=material_type.value,
                    source="user_specified",
                )

            report = self._run_workflow(
                req=req,
                status_callback=status_callback,
                item_callback=item_callback,
            )
            if classification_info is not None:
                report = report.model_copy(
                    update={"material_classification": classification_info}
                )
            reports.append(report)
            trace.extend(report.status_trace)

            done_event = StatusEvent(
                at=datetime.utcnow(),
                stage="输入编排层",
                detail=(
                    f"done_source={idx}/{total}, source={source.source_name}, "
                    f"items={report.summary.total_items}, supported={report.supported}"
                ),
                operation="checking",
            )
            _emit_status(status_callback, done_event)
            trace.append(done_event)

        task_id = f"task_{uuid4().hex[:10]}"
        summary = _aggregate_summary(reports)
        final_event = StatusEvent(
            at=datetime.utcnow(),
            stage="最终报告输出",
            detail=(
                f"sources={len(reports)}, total_items={summary.total_items}, "
                f"unsupported={summary.unsupported_count}"
            ),
            operation="reporting",
        )
        _emit_status(status_callback, final_event)
        trace.append(final_event)

        return BatchSkillReviewReport(
            task_id=task_id,
            source_count=len(reports),
            summary=summary,
            reports=reports,
            status_trace=trace,
        )

    def _classify_source(
        self,
        source: IngestSource,
        user: str,
        *,
        hint_material_type: MaterialType | None = None,
    ) -> tuple[AutoClassification, StatusEvent]:
        try:
            result = self.classifier.classify(
                user=user,
                source_name=source.source_name,
                input_text=source.input_text,
                local_path=source.local_path,
                hint_material_type=hint_material_type,
            )
            event = StatusEvent(
                at=datetime.utcnow(),
                stage="物料自动分类",
                detail=(
                    f"source={source.source_name}, "
                    f"material_type={result.material_type.value}, "
                    f"confidence={result.confidence:.2f}, "
                    f"method={result.source}, "
                    f"model_stage={result.model_stage or 'unknown'}, "
                    f"route={result.route or '-'}, "
                    f"parser={result.parser or '-'}, "
                    f"parse_confidence={result.parse_confidence:.2f}, "
                    f"user_hint={hint_material_type.value if hint_material_type is not None else '-'}, "
                    f"hint_conflict={result.hint_conflict}, "
                    f"ambiguous_pair={result.ambiguous_pair or '-'}, "
                    f"escalated_to_big={result.escalated_to_big}, "
                    f"decision_reasons={','.join(result.decision_reasons) if result.decision_reasons else '-'}, "
                ),
                operation="analyzing",
            )
        except Exception as exc:
            event = StatusEvent(
                at=datetime.utcnow(),
                stage="物料自动分类",
                detail=f"classification_error={exc}",
                operation="analyzing",
            )
            raise ValueError(f"自动分类失败: {exc}") from exc
        return result, event

    def _run_workflow(
        self,
        req: ComplianceRequest,
        status_callback: Callable[[StatusEvent], None] | None = None,
        item_callback: Callable[[SkillMeta, SkillCheckItem], None] | None = None,
    ) -> SkillReviewReport:
        if self._workflow_accepts_status_callback:
            kwargs: dict[str, object] = {"status_callback": status_callback}
            if self._workflow_accepts_item_callback:
                kwargs["item_callback"] = item_callback
            return self.workflow.run(req, **kwargs)
        return self.workflow.run(req)


def aggregate_source_reports(entries: list[SkillReviewReport]) -> BatchSkillSummary:
    return _aggregate_summary(entries)


def _aggregate_summary(reports: list[SkillReviewReport]) -> BatchSkillSummary:
    risk_count = 0
    no_risk_count = 0
    total_items = 0
    supported_count = 0
    unsupported_count = 0

    for report in reports:
        risk_count += report.summary.risk_count
        no_risk_count += report.summary.no_risk_count
        total_items += report.summary.total_items
        if report.supported:
            supported_count += 1
        else:
            unsupported_count += 1

    return BatchSkillSummary(
        risk_count=risk_count,
        no_risk_count=no_risk_count,
        total_items=total_items,
        supported_count=supported_count,
        unsupported_count=unsupported_count,
    )


def _build_request(
    source: IngestSource,
    user: str,
    material_type: MaterialType,
    classification: AutoClassification | None = None,
    context_text: str | None = None,
) -> ComplianceRequest:
    input_file: UploadFile | None = None
    if source.local_path or source.upload_file_id:
        input_file = UploadFile(
            local_path=source.local_path,
            upload_file_id=source.upload_file_id,
        )
        if source.local_path:
            input_file.type = _detect_file_type(source.local_path)

    query = (context_text or "").strip()

    return ComplianceRequest(
        user=user or "anonymous",
        query=query,
        material_type=material_type,
        input_text=source.input_text,
        input_file=input_file,
        contract_type=classification.contract_type
        if classification and material_type == MaterialType.CONTRACT
        else None,
        statement=classification.statement
        if classification and material_type == MaterialType.CONTRACT
        else None,
        scale=classification.scale
        if classification and material_type == MaterialType.CONTRACT
        else None,
        extra={"source_name": source.source_name},
    )


def _detect_file_type(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith(".pdf"):
        return "pdf"
    if lowered.endswith(".docx"):
        return "docx"
    if lowered.endswith(".doc"):
        return "doc"
    if lowered.endswith((".xlsx", ".xlsm")):
        return "xlsx"
    if lowered.endswith(".zip"):
        return "zip"
    if lowered.endswith(
        (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")
    ):
        return "image"
    if lowered.endswith(
        (
            ".txt",
            ".md",
            ".csv",
            ".json",
            ".yaml",
            ".yml",
            ".xml",
            ".html",
            ".htm",
            ".log",
        )
    ):
        return "text"
    return "document"


def _emit_status(
    callback: Callable[[StatusEvent], None] | None,
    event: StatusEvent,
) -> None:
    if callback is None:
        return
    try:
        callback(event)
    except Exception:
        return
