from __future__ import annotations

import asyncio
import inspect
import json
import tempfile
import threading
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile as FastAPIUploadFile
from fastapi.responses import StreamingResponse
import uvicorn

from compliance_agent.config import settings
from compliance_agent.graph.runner import ComplianceWorkflow
from compliance_agent.models.schemas import (
    AssistantRequest,
    AssistantResponse,
    BatchSkillReviewReport,
    BatchSkillSummary,
    ComplianceRequest,
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationMessage,
    ConversationMessagesResponse,
    ConversationSummary,
    MaterialType,
    SkillCheckItem,
    SkillMeta,
    SkillReviewReport,
    StatusEvent,
    normalize_material_type,
)
from compliance_agent.skills.registry import SUPPORTED_MATERIAL_TYPES, SUPPORTED_MATERIAL_TYPE_OPTIONS
from compliance_agent.services.ingest_service import IngestReviewService, IngestSource
from compliance_agent.standalone.assistant_service import AssistantService
from compliance_agent.standalone.conversation_memory_service import ConversationMemoryService, SqliteConversationStore
from compliance_agent.standalone.report_analysis_service import ReportAnalysisService

app = FastAPI(title="Compliance Agent API", version=settings.app_version)
workflow = ComplianceWorkflow()
ingest_service = IngestReviewService(workflow=workflow)
report_analysis_service = ReportAnalysisService()
conversation_store = SqliteConversationStore(settings.conversation_db_path)
conversation_memory = ConversationMemoryService(
    conversation_store,
    default_context_messages=settings.conversation_context_messages,
    default_context_chars=settings.conversation_context_chars,
)
assistant_service = AssistantService(
    ingest_service=ingest_service,
    conversation_memory=conversation_memory,
    analysis_service=report_analysis_service,
)

_ALLOWED_MANUAL_MATERIAL_TYPES = SUPPORTED_MATERIAL_TYPES

_AUTO_CLASSIFY_SENTINEL = None  # material_type not provided → auto-classify


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "compliance-agent",
        "version": settings.app_version,
        "build": settings.app_build,
    }


@app.post("/v1/conversations", response_model=ConversationSummary)
def create_conversation(req: ConversationCreateRequest) -> dict:
    created = conversation_memory.create_conversation(
        user=req.user or "anonymous",
        title=req.title,
    )
    payload = ConversationSummary(
        conversation_id=created.conversation_id,
        user=created.user,
        title=created.title,
        created_at=created.created_at,
        updated_at=created.updated_at,
        last_message_at=created.last_message_at,
    )
    return payload.model_dump(mode="json")


@app.get("/v1/conversations", response_model=ConversationListResponse)
def list_conversations(
    user: str = Query(default="anonymous"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    rows = conversation_memory.list_conversations(
        user=user or "anonymous",
        limit=limit,
        offset=offset,
    )
    payload = ConversationListResponse(
        conversations=[
            ConversationSummary(
                conversation_id=row.conversation_id,
                user=row.user,
                title=row.title,
                created_at=row.created_at,
                updated_at=row.updated_at,
                last_message_at=row.last_message_at,
            )
            for row in rows
        ]
    )
    return payload.model_dump(mode="json")


@app.get("/v1/conversations/{conversation_id}/messages", response_model=ConversationMessagesResponse)
def list_conversation_messages(
    conversation_id: str,
    user: str = Query(default="anonymous"),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    try:
        rows = conversation_memory.list_messages(
            conversation_id=conversation_id,
            user=user or "anonymous",
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    payload = ConversationMessagesResponse(
        conversation_id=conversation_id,
        user=user or "anonymous",
        messages=[
            ConversationMessage(
                message_id=row.message_id,
                conversation_id=row.conversation_id,
                role=row.role,
                content=row.content,
                attachments=row.attachments,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )
    return payload.model_dump(mode="json")


@app.delete("/v1/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user: str = Query(default="anonymous")) -> dict:
    deleted = conversation_memory.delete_conversation(
        conversation_id=conversation_id,
        user=user or "anonymous",
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="conversation 不存在或无权限")
    return {"ok": True}


@app.post("/v1/review", deprecated=True, response_model=SkillReviewReport)
def review(req: ComplianceRequest) -> dict:
    report = workflow.run(req)
    return report.model_dump(mode="json")


@app.post("/v1/assistant", response_model=AssistantResponse)
def assistant(req: AssistantRequest) -> dict:
    try:
        result = assistant_service.handle(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@app.post("/v1/assistant/stream")
async def assistant_stream(req: AssistantRequest) -> StreamingResponse:
    stream = _run_assistant_stream(req)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/v1/review/ingest", response_model=BatchSkillReviewReport)
async def review_ingest(
    files: list[FastAPIUploadFile] | None = File(default=None),
    text: str | None = Form(default=None),
    text_as_source: bool | None = Form(default=None),
    material_type: str | None = Form(default=None),
    user: str = Form(default="anonymous"),
    conversation_id: str | None = Form(default=None),
) -> dict:
    normalized_user = user or "anonymous"
    selected_material = _parse_optional_material_type(material_type)
    normalized_text = (text or "").strip()
    if not files and not normalized_text:
        raise HTTPException(status_code=400, detail="请至少提供一个文件或非空文本")

    if conversation_id:
        try:
            conversation_memory.ensure_conversation(
                conversation_id=conversation_id,
                user=normalized_user,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    with tempfile.TemporaryDirectory(prefix="compliance_ingest_") as tmp_dir:
        sources = await _build_sources(
            files=files or [],
            text=normalized_text,
            tmp_dir=Path(tmp_dir),
            text_as_source=text_as_source,
        )
        try:
            report = await asyncio.to_thread(
                _call_ingest_review_sources,
                sources=sources,
                material_type=selected_material,
                user=normalized_user,
                context_text=_shared_context_text(files or [], normalized_text),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        report = await asyncio.to_thread(_attach_report_analysis, report)
        if conversation_id:
            _save_ingest_turn(
                conversation_id=conversation_id,
                user=normalized_user,
                text=normalized_text,
                sources=sources,
                report=report.model_dump(mode="json"),
            )
        return report.model_dump(mode="json")


@app.post("/v1/review/ingest/stream")
async def review_ingest_stream(
    files: list[FastAPIUploadFile] | None = File(default=None),
    text: str | None = Form(default=None),
    text_as_source: bool | None = Form(default=None),
    material_type: str | None = Form(default=None),
    user: str = Form(default="anonymous"),
    conversation_id: str | None = Form(default=None),
) -> StreamingResponse:
    normalized_user = user or "anonymous"
    selected_material = _parse_optional_material_type(material_type)
    normalized_text = (text or "").strip()
    if not files and not normalized_text:
        raise HTTPException(status_code=400, detail="请至少提供一个文件或非空文本")

    if conversation_id:
        try:
            conversation_memory.ensure_conversation(
                conversation_id=conversation_id,
                user=normalized_user,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    stream = _run_ingest_stream(
        files=files or [],
        text=normalized_text,
        text_as_source=text_as_source,
        material_type=selected_material,
        user=normalized_user,
        conversation_id=conversation_id,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _build_sources(
    files: list[FastAPIUploadFile],
    text: str,
    tmp_dir: Path,
    text_as_source: bool | None = None,
    status_callback: Callable[[StatusEvent], None] | None = None,
) -> list[IngestSource]:
    sources: list[IngestSource] = []

    for idx, upload in enumerate(files, start=1):
        safe_name = Path(upload.filename or f"upload_{idx}.bin").name
        _emit_status(
            status_callback,
            stage="上传文件中",
            detail=f"start_file={idx}/{len(files)}, file={safe_name}",
            operation="uploading",
        )
        target_path = tmp_dir / f"{idx:03d}_{safe_name}"
        bytes_written = 0
        with target_path.open("wb") as fh:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                bytes_written += len(chunk)
        await upload.close()
        _emit_status(
            status_callback,
            stage="上传文件中",
            detail=f"done_file={idx}/{len(files)}, file={safe_name}, bytes={bytes_written}",
            operation="uploading",
        )

        sources.append(
            IngestSource(
                source_name=safe_name,
                source_type="file",
                local_path=str(target_path),
            )
        )

    if text:
        if _should_add_text_source(files=files, text_as_source=text_as_source):
            _emit_status(
                status_callback,
                stage="输入编排层",
                detail=f"inline_text_chars={len(text)}",
                operation="uploading",
            )
            sources.append(
                IngestSource(
                    source_name="inline_text_1",
                    source_type="text",
                    input_text=text,
                )
            )
        else:
            _emit_status(
                status_callback,
                stage="输入编排层",
                detail=(
                    f"shared_context_text_chars={len(text)}, "
                    f"text_as_source_ignored={bool(files) and text_as_source is not None}"
                ),
                operation="analyzing",
            )

    return sources


class _IncrementalReportState:
    def __init__(self) -> None:
        self.risk_count = 0
        self.no_risk_count = 0
        self.total_items = 0
        self.sources: set[str] = set()

    def add_item(self, meta: SkillMeta, item: SkillCheckItem) -> dict[str, Any]:
        source_key = meta.source or meta.input_file or meta.skill_name
        self.sources.add(source_key)
        self.total_items += 1
        status = _classify_stream_item(item.result)
        if status == "risk":
            self.risk_count += 1
        elif status == "no_risk":
            self.no_risk_count += 1

        summary = BatchSkillSummary(
            risk_count=self.risk_count,
            no_risk_count=self.no_risk_count,
            total_items=self.total_items,
            supported_count=len(self.sources),
            unsupported_count=0,
        )
        return {
            "meta": meta.model_dump(mode="json"),
            "item": item.model_dump(mode="json"),
            "summary": summary.model_dump(mode="json"),
            "source_count": len(self.sources),
        }


async def _run_ingest_stream(
    files: list[FastAPIUploadFile],
    text: str,
    text_as_source: bool | None,
    material_type: MaterialType | None,
    user: str,
    conversation_id: str | None = None,
) -> AsyncGenerator[str, None]:
    event_queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def push(event_type: str, payload: dict) -> None:
        loop.call_soon_threadsafe(event_queue.put_nowait, (event_type, payload))

    def status_callback(event: StatusEvent) -> None:
        push("status", event.model_dump(mode="json"))

    with tempfile.TemporaryDirectory(prefix="compliance_ingest_stream_") as tmp_dir:
        try:
            sources = await _build_sources(
                files=files,
                text=text,
                tmp_dir=Path(tmp_dir),
                text_as_source=text_as_source,
                status_callback=status_callback,
            )
        except Exception as exc:
            yield _format_sse(
                "error",
                {
                    "message": str(exc),
                    "stage": "上传文件中",
                },
            )
            yield _format_sse("done", {"ok": False})
            return

        def worker() -> None:
            worker_ok = True
            incremental_state = _IncrementalReportState()

            def item_callback(meta: SkillMeta, item: SkillCheckItem) -> None:
                push("report_item", incremental_state.add_item(meta, item))

            def analysis_chunk_callback(delta: str) -> None:
                push("analysis_chunk", {"delta": delta})

            try:
                report = _call_ingest_review_sources(
                    sources=sources,
                    material_type=material_type,
                    user=user,
                    context_text=_shared_context_text(files, text),
                    status_callback=status_callback,
                    item_callback=item_callback,
                )
                push(
                    "status",
                    StatusEvent(
                        stage="报告解读生成",
                        detail=f"items={report.summary.total_items}, enabled={settings.enable_llm_report_analysis}",
                        operation="model_calling",
                    ).model_dump(mode="json"),
                )
                report = _attach_report_analysis(report, chunk_callback=analysis_chunk_callback)
                push(
                    "status",
                    StatusEvent(
                        stage="报告解读生成",
                        detail=(
                            f"generated_by_model={bool(report.analysis and report.analysis.generated_by_model)}, "
                            f"based_on_items={report.analysis.based_on_items if report.analysis else 0}"
                        ),
                        operation="reporting",
                    ).model_dump(mode="json"),
                )
                if conversation_id:
                    _save_ingest_turn(
                        conversation_id=conversation_id,
                        user=user,
                        text=text,
                        sources=sources,
                        report=report.model_dump(mode="json"),
                    )
                push("report", report.model_dump(mode="json"))
                push(
                    "status",
                    StatusEvent(
                        stage="任务完成",
                        detail=f"task_id={report.task_id}",
                        operation="completed",
                    ).model_dump(mode="json"),
                )
            except Exception as exc:  # pragma: no cover - network and parser failures are environment-dependent
                worker_ok = False
                push(
                    "error",
                    {
                        "message": str(exc),
                        "stage": "检测中",
                    },
                )
            finally:
                push("done", {"ok": worker_ok})

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        while True:
            event_type, payload = await event_queue.get()
            yield _format_sse(event_type, payload)
            if event_type == "done":
                break


async def _run_assistant_stream(req: AssistantRequest) -> AsyncGenerator[str, None]:
    event_queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def push(event_type: str, payload: dict) -> None:
        loop.call_soon_threadsafe(event_queue.put_nowait, (event_type, payload))

    def status_callback(event: StatusEvent) -> None:
        push("status", event.model_dump(mode="json"))

    def worker() -> None:
        worker_ok = True
        incremental_state = _IncrementalReportState()

        def report_item_callback(meta: SkillMeta, item: SkillCheckItem) -> None:
            push("report_item", incremental_state.add_item(meta, item))

        def analysis_chunk_callback(delta: str) -> None:
            push("analysis_chunk", {"delta": delta})

        def chat_chunk_callback(delta: str) -> None:
            push("chat_chunk", {"delta": delta})

        try:
            result = _call_assistant_handle(
                req=req,
                status_callback=status_callback,
                report_item_callback=report_item_callback,
                analysis_chunk_callback=analysis_chunk_callback,
                chat_chunk_callback=chat_chunk_callback,
            )
            push("result", result.model_dump(mode="json"))
        except ValueError as exc:
            worker_ok = False
            push(
                "error",
                {
                    "message": str(exc),
                    "stage": "参数校验",
                },
            )
        except Exception as exc:  # pragma: no cover - network/provider failures are environment-dependent
            worker_ok = False
            push(
                "error",
                {
                    "message": str(exc),
                    "stage": "助手处理",
                },
            )
        finally:
            push("done", {"ok": worker_ok})

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    while True:
        event_type, payload = await event_queue.get()
        yield _format_sse(event_type, payload)
        if event_type == "done":
            break


def _emit_status(
    callback: Callable[[StatusEvent], None] | None,
    *,
    stage: str,
    detail: str,
    operation: str,
) -> None:
    if callback is None:
        return
    try:
        callback(
            StatusEvent(
                stage=stage,
                detail=detail,
                operation=operation,
            )
        )
    except Exception:
        return


def _format_sse(event: str, data: dict) -> str:
    body = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n"


def _parse_optional_material_type(raw_value: str | None) -> MaterialType | None:
    """Parse material_type from form. Returns None to trigger auto-classification."""
    value = (raw_value or "").strip()
    if not value:
        return None  # auto-classify
    options = SUPPORTED_MATERIAL_TYPE_OPTIONS
    parsed = normalize_material_type(value)
    if parsed is None:
        raise HTTPException(status_code=400, detail=f"invalid material_type: {value}, allowed: {options}")
    if parsed not in _ALLOWED_MANUAL_MATERIAL_TYPES:
        raise HTTPException(status_code=400, detail=f"invalid material_type: {value}, allowed: {options}")
    return parsed


def _should_add_text_source(
    files: list[FastAPIUploadFile],
    text_as_source: bool | None,
) -> bool:
    del text_as_source
    # `text_as_source` is preserved for backward compatibility, but text never
    # becomes an extra skill review source when files are present.
    return len(files) == 0


def _shared_context_text(
    files: list[FastAPIUploadFile],
    text: str,
) -> str | None:
    normalized_text = (text or "").strip()
    if not files or not normalized_text:
        return None
    return normalized_text


def _attach_report_analysis(
    report: BatchSkillReviewReport,
    chunk_callback: Callable[[str], None] | None = None,
) -> BatchSkillReviewReport:
    if chunk_callback is not None:
        analysis = report_analysis_service.analyze_stream(report, chunk_callback=chunk_callback)
    else:
        analysis = report_analysis_service.analyze(report)
    return report.model_copy(update={"analysis": analysis})


def _classify_stream_item(result: str) -> str:
    text = (result or "").strip()
    if not text:
        return "unknown"
    if "不存在风险" in text or "不提出风险" in text or "无风险" in text:
        return "no_risk"
    if "提出风险" in text or "存在风险" in text:
        return "risk"
    return "unknown"


def _call_ingest_review_sources(
    *,
    sources: list[IngestSource],
    material_type: MaterialType | None,
    user: str,
    context_text: str | None,
    status_callback: Callable[[StatusEvent], None] | None = None,
    item_callback: Callable[[SkillMeta, SkillCheckItem], None] | None = None,
) -> BatchSkillReviewReport:
    params = inspect.signature(ingest_service.review_sources).parameters
    kwargs: dict[str, Any] = {
        "sources": sources,
        "material_type": material_type,
        "user": user,
        "context_text": context_text,
    }
    if "status_callback" in params:
        kwargs["status_callback"] = status_callback
    if "item_callback" in params:
        kwargs["item_callback"] = item_callback
    return ingest_service.review_sources(**kwargs)


def _call_assistant_handle(
    *,
    req: AssistantRequest,
    status_callback: Callable[[StatusEvent], None] | None = None,
    report_item_callback: Callable[[SkillMeta, SkillCheckItem], None] | None = None,
    analysis_chunk_callback: Callable[[str], None] | None = None,
    chat_chunk_callback: Callable[[str], None] | None = None,
):
    params = inspect.signature(assistant_service.handle).parameters
    kwargs: dict[str, Any] = {"req": req}
    if "status_callback" in params:
        kwargs["status_callback"] = status_callback
    if "report_item_callback" in params:
        kwargs["report_item_callback"] = report_item_callback
    if "analysis_chunk_callback" in params:
        kwargs["analysis_chunk_callback"] = analysis_chunk_callback
    if "chat_chunk_callback" in params:
        kwargs["chat_chunk_callback"] = chat_chunk_callback
    return assistant_service.handle(**kwargs)


def _save_ingest_turn(
    *,
    conversation_id: str,
    user: str,
    text: str,
    sources: list[IngestSource],
    report: dict[str, Any],
) -> None:
    user_content = _build_ingest_user_content(text=text, sources=sources)
    assistant_content = _build_ingest_assistant_content(report)
    user_attachments = _build_ingest_source_attachments(sources)
    assistant_attachments = [
        {
            "type": "report_summary",
            "source_count": report.get("source_count"),
            "summary": report.get("summary"),
        }
    ]
    conversation_memory.append_turn(
        conversation_id=conversation_id,
        user=user or "anonymous",
        user_content=user_content,
        assistant_content=assistant_content,
        user_attachments=user_attachments,
        assistant_attachments=assistant_attachments,
    )


def _build_ingest_user_content(*, text: str, sources: list[IngestSource]) -> str:
    normalized_text = (text or "").strip()
    file_names = [item.source_name for item in sources if item.source_type == "file"]
    if file_names:
        file_hint = ", ".join(file_names[:5])
        if len(file_names) > 5:
            file_hint = f"{file_hint} ... (+{len(file_names) - 5})"
        file_part = f"[上传文件] {file_hint}"
        if normalized_text:
            return f"{normalized_text}\n\n{file_part}"
        return file_part
    if normalized_text:
        return normalized_text
    return "请执行合规检测"


def _build_ingest_assistant_content(report: dict[str, Any]) -> str:
    analysis = report.get("analysis") if isinstance(report, dict) else None
    if isinstance(analysis, dict):
        summary_markdown = str(analysis.get("summary_markdown") or "").strip()
        if summary_markdown:
            return f"已完成合规检测，以下是报告解读：\n\n{summary_markdown}"

    summary = report.get("summary") if isinstance(report, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    total_items = int(summary.get("total_items") or 0)
    risk_count = int(summary.get("risk_count") or 0)
    pass_count = int(summary.get("no_risk_count") or 0)
    source_count = int(report.get("source_count") or 0)
    if total_items <= 0:
        return (
            f"已完成 {source_count} 份输入的合规检测，暂未解析出有效检测项。"
            "如需我可继续细化某一份材料的专项审查。"
        )
    return (
        f"已完成 {source_count} 份输入的合规检测，"
        f"共 {total_items} 条检测项，其中风险 {risk_count} 条、通过 {pass_count} 条。"
    )


def _build_ingest_source_attachments(sources: list[IngestSource]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in sources:
        output.append(
            {
                "source_name": item.source_name,
                "source_type": item.source_type,
                "has_local_path": bool(item.local_path),
                "has_input_text": bool(item.input_text),
            }
        )
    return output


def run() -> None:
    uvicorn.run("compliance_agent.api.app:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
