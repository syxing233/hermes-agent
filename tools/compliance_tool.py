"""Embedded compliance review tools for Hermes.

These tools call the in-process ``compliance_agent`` runtime directly. Hermes
remains the only assistant/session layer; the embedded engine only produces
structured compliance facts and review artifacts.
"""

from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
from typing import Any

from compliance_agent.hermes.request_adapter import (
    adapt_review_request,
    coerce_file_paths,
    normalize_material_type_hint,
)
from compliance_agent.hermes.result_adapter import (
    adapt_artifact_payload,
    adapt_review_result,
)
from compliance_agent.hermes.runtime import get_runtime
from compliance_agent.hermes.session_policy import should_store_review_in_memory
from tools.registry import registry, tool_error, tool_result


def check_compliance_agent_requirements() -> bool:
    return True


def _normalize_material_type(value: Any) -> str | None:
    normalized = normalize_material_type_hint(value)
    return normalized.value if normalized is not None else None


def _coerce_file_paths(file_paths: Any, cwd: Path | str | None = None) -> list[Path]:
    return coerce_file_paths(file_paths, cwd=cwd)


def _build_upload_file_payload(path: Path) -> dict[str, str]:
    guessed_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    upload_type = "image" if guessed_type.startswith("image/") else "document"
    return {
        "type": upload_type,
        "transfer_method": "local_file",
        "local_path": str(path),
    }


def _apply_timeout_override(timeout_seconds: int | None) -> None:
    if not timeout_seconds:
        return

    runtime = get_runtime()
    workflow_client = getattr(runtime, "workflow_client", None)
    workflow_http_client = getattr(workflow_client, "_client", None)
    if workflow_http_client is not None:
        workflow_http_client.timeout = timeout_seconds
    classifier = getattr(runtime, "classifier", None)
    if hasattr(classifier, "request_timeout_seconds"):
        classifier.request_timeout_seconds = float(timeout_seconds)


def compliance_health(timeout_seconds: int = 10) -> str:
    try:
        _apply_timeout_override(timeout_seconds)
        runtime = get_runtime()
    except Exception as exc:
        return tool_error(
            f"Embedded compliance runtime failed to initialize: {exc}", success=False
        )

    health = runtime.health_payload()
    return tool_result(
        success=True,
        service="embedded-compliance-engine",
        version=runtime.settings.app_version,
        build=runtime.settings.app_build,
        health=health,
    )


def compliance_review(
    file_paths: Any = None,
    text: str | None = None,
    material_type: str | None = None,
    user: str = "anonymous",
    conversation_id: str | None = None,
    text_as_source: bool = False,
    timeout_seconds: int = 120,
) -> str:
    cwd_override = os.getenv("TERMINAL_CWD")
    try:
        request = adapt_review_request(
            file_paths=file_paths,
            text=text,
            material_type=material_type,
            user=user,
            conversation_id=conversation_id,
            text_as_source=text_as_source,
            cwd=cwd_override,
        )
    except (FileNotFoundError, ValueError, PermissionError) as exc:
        return tool_error(str(exc), success=False)

    try:
        _apply_timeout_override(timeout_seconds)
        runtime = get_runtime()
        from compliance_agent.hermes.progress_bridge import HermesProgressBridge

        progress = HermesProgressBridge()
        report = runtime.ingest_service.review_sources(
            request.sources,
            material_type=request.material_type,
            hint_material_type=request.hint_material_type,
            user=request.user,
            context_text=request.context_text,
            status_callback=progress.status_callback,
            item_callback=progress.item_callback,
        )
        compact = adapt_review_result(report, artifact_path=None, progress=progress)
        artifact = runtime.artifact_store.persist_review(report, compact_result=compact)
    except FileNotFoundError as exc:
        return tool_error(
            f"File not found during compliance review: {exc}", success=False
        )
    except ValueError as exc:
        return tool_error(
            f"Invalid input during compliance review: {exc}", success=False
        )
    except Exception as exc:
        import traceback

        tb_lines = traceback.format_exception(type(exc), exc, exc.__cause__)
        short_tb = "".join(tb_lines[-3:])
        return tool_error(
            f"Embedded compliance review failed: {exc}\nDetails: {short_tb}",
            success=False,
        )

    compact["artifact_path"] = artifact.json_path if artifact is not None else None
    if artifact is not None and artifact.markdown_path:
        compact["artifact_markdown_path"] = artifact.markdown_path
    compact["uses_standalone_memory"] = False
    compact["session_memory_policy"] = (
        "artifact_only" if not should_store_review_in_memory() else "session"
    )
    if conversation_id:
        compact["conversation_id"] = conversation_id

    return tool_result(compact)


def compliance_assistant(
    message: str | None = None,
    input_text: str | None = None,
    material_type: str | None = None,
    user: str = "anonymous",
    conversation_id: str | None = None,
    input_file_path: str | None = None,
    timeout_seconds: int = 120,
) -> str:
    normalized_message = (message or "").strip()
    normalized_input_text = (input_text or "").strip()
    normalized_file_path = (input_file_path or "").strip()

    if (
        not normalized_message
        and not normalized_input_text
        and not normalized_file_path
    ):
        return tool_error(
            "Provide message, input_text, or input_file_path for the compliance assistant.",
            success=False,
        )

    if normalized_input_text or normalized_file_path:
        merged_text = normalized_input_text
        if normalized_message:
            merged_text = (
                f"{normalized_input_text}\n\n补充要求：{normalized_message}"
                if normalized_input_text
                else normalized_message
            )

        review_payload = json.loads(
            compliance_review(
                file_paths=[normalized_file_path] if normalized_file_path else None,
                text=merged_text or None,
                material_type=material_type,
                user=user,
                conversation_id=conversation_id,
                text_as_source=not bool(normalized_file_path),
                timeout_seconds=timeout_seconds,
            )
        )
        if review_payload.get("error"):
            return tool_result(review_payload)

        return tool_result(
            success=True,
            mode="detection",
            reply="已通过 Hermes 内嵌合规引擎执行检测。",
            material_type=review_payload.get("material_type"),
            review_id=review_payload.get("review_id"),
            conversation_id=conversation_id,
            report_summary=review_payload.get("summary"),
            top_items=review_payload.get("top_items", []),
            artifact_path=review_payload.get("artifact_path"),
            uses_standalone_memory=False,
            deprecated=True,
        )

    return tool_result(
        success=True,
        mode="compatibility",
        reply=(
            "内嵌版本不再维护独立 compliance assistant 会话。"
            "请直接提供文件路径或待审文本，并优先使用 compliance_review。"
        ),
        conversation_id=conversation_id,
        uses_standalone_memory=False,
        deprecated=True,
    )


def compliance_get_report(
    review_id: str,
    include_full_report: bool = False,
) -> str:
    try:
        runtime = get_runtime()
        artifact_path, payload = runtime.artifact_store.read_review(review_id)
        result = adapt_artifact_payload(
            payload, include_full_report=include_full_report
        )
        result["artifact_path"] = str(artifact_path)
        return tool_result(result)
    except Exception as exc:
        return tool_error(
            f"Unable to load compliance report '{review_id}': {exc}", success=False
        )


COMPLIANCE_HEALTH_SCHEMA = {
    "name": "compliance_health",
    "description": (
        "Check the embedded compliance engine configuration inside Hermes. "
        "Use this to confirm the in-process runtime, workflow endpoint, and artifact store wiring."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "timeout_seconds": {
                "type": "integer",
                "description": "Optional timeout override for embedded workflow clients.",
                "default": 10,
            },
        },
    },
}

COMPLIANCE_REVIEW_SCHEMA = {
    "name": "compliance_review",
    "description": (
        "Run structured compliance review with Hermes's embedded compliance engine. "
        "Use this for files or text that need classification, material routing, external workflow execution, "
        "and a compact result with a stored artifact. "
        "If the user attached a local PDF, Word document, image, or other saved file and wants compliance checking, "
        "call this tool directly with that local path. Do not ask the user to paste text or convert the file first "
        "when an accessible local path is already available. "
        "The file is uploaded to the external workflow API automatically — you only need to pass the local path string."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file_paths": {
                "type": ["array", "string"],
                "items": {"type": "string"},
                "description": "One or more accessible local file paths for compliance review. Pass the EXACT path shown in the user message (e.g. '/Users/user/Documents/file.pdf'). The file is uploaded to the workflow API internally — do not ask the user to convert or paste content.",
            },
            "text": {
                "type": "string",
                "description": "Inline text to review, or brief contextual instructions for attached files. Do not require the user to paste document text when file_paths already points to the file.",
            },
            "material_type": {
                "type": "string",
                "description": "Optional material type hint. Supports Chinese labels and aliases like contract/poster/marketing.",
            },
            "user": {
                "type": "string",
                "description": "Logical user identifier attached to the embedded review request.",
                "default": "anonymous",
            },
            "conversation_id": {
                "type": "string",
                "description": "Optional Hermes-side session identifier kept as metadata only. No separate compliance conversation is created.",
            },
            "text_as_source": {
                "type": "boolean",
                "description": "When true, treat `text` as its own review source instead of contextual text for files.",
                "default": False,
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Optional timeout override for the embedded compliance clients.",
                "default": 120,
            },
        },
    },
}

COMPLIANCE_ASSISTANT_SCHEMA = {
    "name": "compliance_assistant",
    "description": (
        "Compatibility wrapper for legacy compliance-assistant flows. "
        "This no longer creates an independent assistant or memory store; it either forwards to compliance_review "
        "or tells the caller to use compliance_review directly."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Legacy user request text for compatibility flows.",
            },
            "input_text": {
                "type": "string",
                "description": "Inline text to review through the embedded engine.",
            },
            "material_type": {
                "type": "string",
                "description": "Optional material type hint.",
            },
            "user": {
                "type": "string",
                "description": "Logical user identifier attached to the request.",
                "default": "anonymous",
            },
            "conversation_id": {
                "type": "string",
                "description": "Legacy compatibility field. Preserved as metadata only.",
            },
            "input_file_path": {
                "type": "string",
                "description": "Local file path for compatibility review routing.",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Optional timeout override for the embedded clients.",
                "default": 120,
            },
        },
    },
}

COMPLIANCE_GET_REPORT_SCHEMA = {
    "name": "compliance_get_report",
    "description": (
        "Load a stored compliance review artifact by review_id. "
        "Use this when you need to inspect a previously stored report without rerunning the review."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "review_id": {
                "type": "string",
                "description": "The review ID returned by compliance_review, or a JSON artifact path.",
            },
            "include_full_report": {
                "type": "boolean",
                "description": "When true, return the full stored report payload. Default is compact metadata only.",
                "default": False,
            },
        },
        "required": ["review_id"],
    },
}


def _handle_compliance_health(args: dict, **kw) -> str:
    return compliance_health(timeout_seconds=args.get("timeout_seconds", 10))


def _handle_compliance_review(args: dict, **kw) -> str:
    return compliance_review(
        file_paths=args.get("file_paths"),
        text=args.get("text"),
        material_type=args.get("material_type"),
        user=args.get("user", "anonymous"),
        conversation_id=args.get("conversation_id"),
        text_as_source=args.get("text_as_source", False),
        timeout_seconds=args.get("timeout_seconds", 120),
    )


def _handle_compliance_assistant(args: dict, **kw) -> str:
    return compliance_assistant(
        message=args.get("message"),
        input_text=args.get("input_text"),
        material_type=args.get("material_type"),
        user=args.get("user", "anonymous"),
        conversation_id=args.get("conversation_id"),
        input_file_path=args.get("input_file_path"),
        timeout_seconds=args.get("timeout_seconds", 120),
    )


def _handle_compliance_get_report(args: dict, **kw) -> str:
    return compliance_get_report(
        review_id=args.get("review_id", ""),
        include_full_report=args.get("include_full_report", False),
    )


registry.register(
    name="compliance_health",
    toolset="compliance",
    schema=COMPLIANCE_HEALTH_SCHEMA,
    handler=_handle_compliance_health,
    check_fn=check_compliance_agent_requirements,
    requires_env=[],
)

registry.register(
    name="compliance_review",
    toolset="compliance",
    schema=COMPLIANCE_REVIEW_SCHEMA,
    handler=_handle_compliance_review,
    check_fn=check_compliance_agent_requirements,
    requires_env=[],
)

registry.register(
    name="compliance_assistant",
    toolset="compliance",
    schema=COMPLIANCE_ASSISTANT_SCHEMA,
    handler=_handle_compliance_assistant,
    check_fn=check_compliance_agent_requirements,
    requires_env=[],
)

registry.register(
    name="compliance_get_report",
    toolset="compliance",
    schema=COMPLIANCE_GET_REPORT_SCHEMA,
    handler=_handle_compliance_get_report,
    check_fn=check_compliance_agent_requirements,
    requires_env=[],
)
