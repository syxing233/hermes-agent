from __future__ import annotations

from collections.abc import Callable
import inspect
import json
from pathlib import Path
import re
from typing import Any

import httpx

from compliance_agent.config import settings
from compliance_agent.models.schemas import (
    AssistantIntentMeta,
    AssistantMode,
    AssistantRequest,
    AssistantResponse,
    BatchSkillReviewReport,
    MaterialType,
    SkillCheckItem,
    SkillMeta,
    StatusEvent,
    normalize_material_type,
)
from compliance_agent.services.external_workflow_client import ExternalWorkflowClient
from compliance_agent.services.ingest_service import IngestReviewService, IngestSource
from compliance_agent.standalone.conversation_memory_service import ConversationMemoryService
from compliance_agent.standalone.report_analysis_service import ReportAnalysisService

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.S)

_CHAT_HINTS = ("闲聊", "聊天", "解释一下", "怎么实现", "如何设计")
_CONTRACT_FEATURE_RE = re.compile(r"第\s*[一二三四五六七八九十百千0-9]+\s*条")

class AssistantService:
    def __init__(
        self,
        ingest_service: IngestReviewService | None = None,
        client: ExternalWorkflowClient | None = None,
        conversation_memory: ConversationMemoryService | None = None,
        analysis_service: ReportAnalysisService | None = None,
    ):
        self.ingest_service = ingest_service or IngestReviewService()
        self.client = client or ExternalWorkflowClient(
            base_url=settings.openai_base_url if settings.openai_api_key else settings.workflow_base_url,
            timeout_seconds=settings.workflow_timeout_seconds,
            max_retries=settings.workflow_max_retries,
        )
        self.conversation_memory = conversation_memory
        self.analysis_service = analysis_service or ReportAnalysisService()

    def handle(
        self,
        req: AssistantRequest,
        status_callback: Callable[[StatusEvent], None] | None = None,
        report_item_callback: Callable[[SkillMeta, SkillCheckItem], None] | None = None,
        analysis_chunk_callback: Callable[[str], None] | None = None,
        chat_chunk_callback: Callable[[str], None] | None = None,
    ) -> AssistantResponse:
        message = (req.message or "").strip()
        input_text = (req.input_text or "").strip()
        if not message and not input_text and not _has_explicit_source(req):
            raise ValueError("message、input_text 或 input_file 至少提供一个")

        req_for_routing = req
        if req.conversation_id and self.conversation_memory is not None:
            context_messages = int(getattr(settings, "conversation_context_messages", 16))
            context_chars = int(getattr(settings, "conversation_context_chars", 12000))
            history = self.conversation_memory.load_chat_context(
                conversation_id=req.conversation_id,
                user=req.user or "anonymous",
                max_messages=context_messages,
                max_chars=context_chars,
            )
            req_for_routing = req.model_copy(update={"history": history})
            _emit_status(
                status_callback,
                stage="会话记忆加载",
                detail=f"conversation_id={req.conversation_id}, context_messages={len(history)}",
                operation="analyzing",
            )

        intent = self._resolve_intent(req=req_for_routing, message=message)
        material_text = intent.material_type.value if intent.material_type is not None else "-"
        requested_material_text = (
            intent.requested_material_type.value if intent.requested_material_type is not None else "-"
        )
        _emit_status(
            status_callback,
            stage="意图识别",
            detail=(
                f"mode={intent.mode.value}, reason={intent.reason}, "
                f"confidence={intent.confidence:.2f}, material_type={material_text}, "
                f"requested_material_type={requested_material_text}"
            ),
            operation="analyzing",
        )
        _emit_status(
            status_callback,
            stage="路由决策",
            detail=f"route={intent.mode.value}",
            operation="checking",
        )

        if intent.mode == AssistantMode.DETECTION:
            result = self._handle_detection(
                req=req_for_routing,
                message=message,
                input_text=input_text,
                intent=intent,
                status_callback=status_callback,
                report_item_callback=report_item_callback,
                analysis_chunk_callback=analysis_chunk_callback,
            )
        else:
            result = self._handle_chat(
                req=req_for_routing,
                message=message,
                intent=intent,
                status_callback=status_callback,
                chat_chunk_callback=chat_chunk_callback,
            )

        if req.conversation_id and self.conversation_memory is not None:
            user_content = (message or input_text).strip()
            assistant_content = result.reply
            if result.report is not None and result.report.analysis is not None:
                analysis_text = result.report.analysis.summary_markdown.strip()
                if analysis_text:
                    assistant_content = analysis_text
            self.conversation_memory.append_turn(
                conversation_id=req.conversation_id,
                user=req.user or "anonymous",
                user_content=user_content,
                assistant_content=assistant_content,
            )
            result = result.model_copy(update={"conversation_id": req.conversation_id})

        _emit_status(
            status_callback,
            stage="回复输出",
            detail=f"mode={result.mode.value}, has_report={result.report is not None}",
            operation="reporting",
        )
        return result

    def _resolve_intent(self, req: AssistantRequest, message: str) -> AssistantIntentMeta:
        requested_material_type = _infer_requested_material_type(req, message)
        if req.material_type is not None:
            return AssistantIntentMeta(
                mode=AssistantMode.DETECTION,
                reason="manual_material_type",
                confidence=1.0,
                material_type=None,
                requested_material_type=requested_material_type,
            )

        has_source = _has_detectable_source(req, message)
        explicit_source = _has_explicit_source(req)
        input_text_excerpt = _build_input_text_excerpt(req.input_text)

        if not message and explicit_source:
            return AssistantIntentMeta(
                mode=AssistantMode.DETECTION,
                reason="source_without_message",
                confidence=1.0,
                material_type=None,
                requested_material_type=requested_material_type,
            )

        if _looks_like_chat_request(message):
            return AssistantIntentMeta(
                mode=AssistantMode.CHAT,
                reason="rule_chat_hint",
                confidence=0.9,
                material_type=None,
            )

        model_intent = self._resolve_intent_by_model(
            message=message,
            input_text_excerpt=input_text_excerpt,
            has_source=has_source,
            history=req.history,
        )
        if model_intent is not None:
            if model_intent.mode == AssistantMode.DETECTION and not has_source:
                return AssistantIntentMeta(
                    mode=AssistantMode.CHAT,
                    reason="no_source_downgrade",
                    confidence=0.85,
                    material_type=None,
                )
            return model_intent.model_copy(update={"requested_material_type": requested_material_type})

        return AssistantIntentMeta(
            mode=AssistantMode.CHAT,
            reason="rule_chat",
            confidence=0.8,
            material_type=None,
        )

    def _resolve_intent_by_model(
        self,
        message: str,
        *,
        input_text_excerpt: str,
        has_source: bool,
        history: list[Any],
    ) -> AssistantIntentMeta | None:
        if not settings.openai_api_key:
            return None

        if not message and not input_text_excerpt:
            return None

        system_parts = [
            f"{settings.system_prompt}\n"
            "你是意图路由器。判断用户消息是普通聊天(chat)还是合规检测(detection)请求。"
            "请区分："
            "检测指令=用户明确要求对某段文字/文件做合规审查，含指令动词，且通常有正文；"
            "内容提问=用户在对话历史基础上提问，\"这份合同\"、\"这个条款\"可能指代上文内容。"
            "如果用户只是提问/解释/咨询，不要判 detection。"
            "只输出 JSON: {intent, confidence, reason}。"
        ]
        if not has_source:
            system_parts.append(
                "当前用户未上传文件也未粘贴正文（has_source=false）。"
                "仅当用户明确说“我有文件/我来上传”时才判 detection，否则判 chat。"
            )
        history_summary = _summarize_recent_history(history)
        if history_summary:
            system_parts.append(f"以下是本次会话的最近对话：\n{history_summary}")

        messages = [
            {
                "role": "system",
                "content": "\n".join(system_parts),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "message": message,
                        "input_text_excerpt": input_text_excerpt,
                        "has_source": has_source,
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        try:
            raw = self.client.run_chat_completions(
                messages=messages,
                api_key=settings.openai_api_key,
                model=settings.model,
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=240,
            )
            payload = _parse_json_payload(raw)
            raw_intent = str(payload.get("intent") or "").strip().lower()
            mode = AssistantMode.DETECTION if raw_intent in {"detection", "detect", "review", "check"} else AssistantMode.CHAT
            return AssistantIntentMeta(
                mode=mode,
                reason=str(payload.get("reason") or "model_intent"),
                confidence=_clamp(payload.get("confidence"), 0.75),
                material_type=None,
            )
        except Exception:
            return None

    def _handle_detection(
        self,
        req: AssistantRequest,
        message: str,
        input_text: str,
        intent: AssistantIntentMeta,
        status_callback: Callable[[StatusEvent], None] | None = None,
        report_item_callback: Callable[[SkillMeta, SkillCheckItem], None] | None = None,
        analysis_chunk_callback: Callable[[str], None] | None = None,
    ) -> AssistantResponse:
        context_text = input_text if req.input_file is not None and input_text else None
        sources = _build_detection_sources(
            req=req,
            message=message,
            input_text=input_text,
            include_input_text_source=context_text is None,
        )
        if not sources:
            raise ValueError("检测模式下缺少可检测内容，请上传文件或粘贴文本")

        requested_material_type = req.material_type or intent.requested_material_type
        requested_material_text = requested_material_type.value if requested_material_type is not None else "-"
        source_names = ",".join(source.source_name for source in sources)
        _emit_status(
            status_callback,
            stage="检测流程调度",
            detail=(
                f"sources={len(sources)}, names={source_names}, requested_material_type={requested_material_text}, "
                f"material_type=auto, "
                f"context_chars={len(context_text or '')}"
            ),
            operation="checking",
        )
        report = self._call_review_sources(
            sources=sources,
            material_type=None,
            hint_material_type=requested_material_type,
            user=req.user or "anonymous",
            context_text=context_text,
            status_callback=status_callback,
            report_item_callback=report_item_callback,
        )
        report = self._attach_report_analysis(
            report=report,
            status_callback=status_callback,
            analysis_chunk_callback=analysis_chunk_callback,
        )

        resolved_material_type = _resolve_report_material_type(report)
        if (
            requested_material_type is not None
            and resolved_material_type is not None
            and requested_material_type != resolved_material_type
        ):
            _emit_status(
                status_callback,
                stage="物料类型裁决",
                detail=(
                    f"requested_material_type={requested_material_type.value}, "
                    f"resolved_material_type={resolved_material_type.value}, source=document_classifier"
                ),
                operation="checking",
            )

        resolved_intent = intent.model_copy(
            update={
                "material_type": resolved_material_type,
                "requested_material_type": requested_material_type,
            }
        )
        return AssistantResponse(
            mode=AssistantMode.DETECTION,
            reply=_build_detection_reply(report),
            intent=resolved_intent,
            report=report,
        )

    def _handle_chat(
        self,
        req: AssistantRequest,
        message: str,
        intent: AssistantIntentMeta,
        status_callback: Callable[[StatusEvent], None] | None = None,
        chat_chunk_callback: Callable[[str], None] | None = None,
    ) -> AssistantResponse:
        if not settings.openai_api_key:
            _emit_status(
                status_callback,
                stage="聊天模型调用",
                detail="OPENAI_API_KEY 未配置，跳过模型调用",
                operation="model_calling",
            )
            return AssistantResponse(
                mode=AssistantMode.CHAT,
                reply="当前未配置 OPENAI_API_KEY，无法调用聊天模型。你可以直接提交检测请求，我会走检测流程。",
                intent=intent,
                report=None,
            )

        system_prompt = (
            f"{settings.system_prompt}\n"
            "你是合规助手：普通咨询直接回答；若用户需要合规检测，提醒可直接提出检测请求。"
        )
        if intent.reason == "no_source_downgrade":
            system_prompt += "用户似乎想进行合规检测但尚未提供材料，请在回答末尾友好提示用户上传文件或粘贴文本。"

        messages = [
            {
                "role": "system",
                "content": system_prompt,
            }
        ]
        for item in req.history[-10:]:
            content = (item.content or "").strip()
            if not content:
                continue
            messages.append({"role": item.role.value, "content": content})

        if message:
            messages.append({"role": "user", "content": message})

        _emit_status(
            status_callback,
            stage="聊天模型调用",
            detail=f"messages={len(messages)}, model={settings.model}",
            operation="model_calling",
        )
        try:
            if chat_chunk_callback is not None:
                chunks: list[str] = []
                for delta in self.client.stream_chat_completions(
                    messages=messages,
                    api_key=settings.openai_api_key,
                    model=settings.model,
                    temperature=0.3,
                    max_tokens=1200,
                ):
                    if not delta:
                        continue
                    chunks.append(delta)
                    chat_chunk_callback(delta)
                answer = "".join(chunks)
            else:
                answer = self.client.run_chat_completions(
                    messages=messages,
                    api_key=settings.openai_api_key,
                    model=settings.model,
                    temperature=0.3,
                    max_tokens=1200,
                )
            _emit_status(
                status_callback,
                stage="聊天模型调用",
                detail="model_call_succeeded",
                operation="model_calling",
            )
        except Exception as exc:
            _emit_status(
                status_callback,
                stage="聊天模型调用",
                detail=f"model_call_failed={exc.__class__.__name__}",
                operation="model_calling",
            )
            answer = _format_chat_error(exc)

        return AssistantResponse(
            mode=AssistantMode.CHAT,
            reply=answer.strip() or "我没有生成有效回复，请重试一次。",
            intent=intent,
            report=None,
        )

    def _attach_report_analysis(
        self,
        *,
        report: BatchSkillReviewReport,
        status_callback: Callable[[StatusEvent], None] | None = None,
        analysis_chunk_callback: Callable[[str], None] | None = None,
    ) -> BatchSkillReviewReport:
        analysis_enabled = bool(getattr(settings, "enable_llm_report_analysis", True))
        _emit_status(
            status_callback,
            stage="报告解读生成",
            detail=f"items={report.summary.total_items}, enabled={analysis_enabled}",
            operation="model_calling",
        )
        if analysis_chunk_callback is not None:
            analysis = self.analysis_service.analyze_stream(
                report=report,
                chunk_callback=analysis_chunk_callback,
            )
        else:
            analysis = self.analysis_service.analyze(report)
        _emit_status(
            status_callback,
            stage="报告解读生成",
            detail=(
                f"generated_by_model={analysis.generated_by_model}, "
                f"based_on_items={analysis.based_on_items}"
            ),
            operation="reporting",
        )
        return report.model_copy(update={"analysis": analysis})

    def _call_review_sources(
        self,
        *,
        sources: list[IngestSource],
        material_type: MaterialType | None,
        hint_material_type: MaterialType | None,
        user: str,
        context_text: str | None,
        status_callback: Callable[[StatusEvent], None] | None = None,
        report_item_callback: Callable[[SkillMeta, SkillCheckItem], None] | None = None,
    ) -> BatchSkillReviewReport:
        params = inspect.signature(self.ingest_service.review_sources).parameters
        kwargs: dict[str, Any] = {
            "sources": sources,
            "material_type": material_type,
            "hint_material_type": hint_material_type,
            "user": user,
            "context_text": context_text,
        }
        if "hint_material_type" not in params:
            kwargs.pop("hint_material_type", None)
        if "status_callback" in params:
            kwargs["status_callback"] = status_callback
        if "item_callback" in params:
            kwargs["item_callback"] = report_item_callback
        return self.ingest_service.review_sources(**kwargs)


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


def _looks_like_chat_request(message: str) -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False
    return any(token in text for token in _CHAT_HINTS)


def _has_explicit_source(req: AssistantRequest) -> bool:
    if (req.input_text or "").strip():
        return True

    input_file = req.input_file
    if input_file is None:
        return False
    return bool((input_file.upload_file_id or "").strip() or (input_file.local_path or "").strip())


def _has_detectable_source(req: AssistantRequest, message: str) -> bool:
    normalized_input_text = (req.input_text or "").strip()
    if normalized_input_text and len(normalized_input_text) >= 30:
        return True

    input_file = req.input_file
    if input_file is not None:
        has_upload_id = bool((input_file.upload_file_id or "").strip())
        has_local_path = bool((input_file.local_path or "").strip())
        if has_upload_id or has_local_path:
            return True

    return _message_has_inline_source(message)


def _summarize_recent_history(history: list[Any], limit: int = 3, content_limit: int = 120) -> str:
    if not history:
        return ""

    rendered: list[str] = []
    for item in history[-limit:]:
        content = str(getattr(item, "content", "") or "").strip()
        if not content:
            continue
        role = getattr(item, "role", "user")
        role_text = str(getattr(role, "value", role) or "user")
        compact = " ".join(content.split())
        if len(compact) > content_limit:
            compact = f"{compact[:content_limit]}..."
        rendered.append(f"{role_text}: {compact}")
    return "\n".join(rendered)


def _message_has_inline_source(message: str) -> bool:
    normalized_message = (message or "").strip()
    if not normalized_message:
        return False

    if "\n" in normalized_message and len(normalized_message) >= 80:
        return True

    has_contract_features = (
        "甲方" in normalized_message
        or "乙方" in normalized_message
        or bool(_CONTRACT_FEATURE_RE.search(normalized_message))
    )
    if has_contract_features and len(normalized_message) >= 60:
        return True

    return False


def _build_input_text_excerpt(input_text: str | None, limit: int = 600) -> str:
    compact = " ".join((input_text or "").split()).strip()
    if not compact:
        return ""
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _infer_requested_material_type(req: AssistantRequest, message: str) -> MaterialType | None:
    if req.material_type is not None:
        return req.material_type
    return _parse_material_type(message)


def _resolve_report_material_type(report: BatchSkillReviewReport) -> MaterialType | None:
    detected_types = {
        parsed
        for parsed in (_parse_material_type(single.meta.material_type) for single in report.reports)
        if parsed is not None
    }
    if len(detected_types) == 1:
        return next(iter(detected_types))
    return None


def _build_detection_sources(
    req: AssistantRequest,
    message: str,
    input_text: str,
    *,
    include_input_text_source: bool = True,
) -> list[IngestSource]:
    sources: list[IngestSource] = []

    input_file = req.input_file
    local_path = (input_file.local_path or "").strip() if input_file is not None else ""
    upload_file_id = (input_file.upload_file_id or "").strip() if input_file is not None else ""
    if local_path:
        source_name = Path(local_path).name or "assistant_file_1"
        sources.append(
            IngestSource(
                source_name=source_name,
                source_type="file",
                local_path=local_path,
            )
        )
    elif upload_file_id:
        sources.append(
            IngestSource(
                source_name=upload_file_id,
                source_type="file",
                upload_file_id=upload_file_id,
            )
        )

    normalized_input_text = (input_text or "").strip()
    if normalized_input_text and include_input_text_source:
        sources.append(
            IngestSource(
                source_name="assistant_text_1",
                source_type="text",
                input_text=normalized_input_text,
            )
        )
    elif _message_has_inline_source(message):
        sources.append(
            IngestSource(
                source_name="assistant_text_1",
                source_type="text",
                input_text=(message or "").strip(),
            )
        )

    if not sources:
        fallback_text = (input_text or message).strip()
        if fallback_text:
            sources.append(
                IngestSource(
                    source_name="assistant_text_1",
                    source_type="text",
                    input_text=fallback_text,
                )
            )

    return sources


def _format_chat_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        hint = _http_status_hint(status)
        summary = _response_error_summary(exc.response)
        if summary:
            return f"聊天模型调用失败: HTTP {status}（{hint}）。服务端返回：{summary}"
        return f"聊天模型调用失败: HTTP {status}（{hint}）。"

    if isinstance(exc, httpx.TimeoutException):
        return "聊天模型调用失败: 请求超时，请稍后重试。"

    if isinstance(exc, httpx.HTTPError):
        return f"聊天模型调用失败: 网络错误（{exc.__class__.__name__}），请稍后重试。"

    return f"聊天模型调用失败: {exc.__class__.__name__}，请稍后重试。"


def _http_status_hint(status: int) -> str:
    if status in {401, 403}:
        return "鉴权失败，请检查 OPENAI_API_KEY 或权限"
    if status == 404:
        return "接口或模型不可用，请检查 OPENAI_BASE_URL 和 MODEL"
    if status == 429:
        return "触发限流，请稍后重试"
    if status >= 500:
        return "上游服务异常，请稍后重试"
    if status == 400:
        return "请求参数错误，请检查模型名或请求格式"
    return "请求失败"


def _response_error_summary(response: httpx.Response, max_len: int = 160) -> str:
    text = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            for key in ("message", "error", "detail", "msg"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    text = value.strip()
                    break
            if not text:
                text = json.dumps(payload, ensure_ascii=False)
        elif payload is not None:
            text = str(payload)
    except Exception:
        text = (response.text or "").strip()

    compact = " ".join(text.split())
    if not compact:
        return ""
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."


def _parse_material_type(value: Any) -> MaterialType | None:
    parsed = normalize_material_type(value)

    if parsed == MaterialType.OTHER:
        return None
    if parsed is not None:
        return parsed

    text = str(value or "").strip()
    if not text:
        return None

    if "合同" in text:
        return MaterialType.CONTRACT
    if "条款" in text:
        return MaterialType.CLAUSE_BOOK
    if "产品说明书" in text or "说明书" in text:
        return MaterialType.HANDBOOK
    if "海报" in text:
        return MaterialType.POSTER
    if "营销" in text or "文案" in text or "宣传" in text:
        return MaterialType.MARKETING
    return None


def _parse_json_payload(raw: str) -> dict[str, Any]:
    candidate = (raw or "").strip()
    if not candidate:
        raise ValueError("empty model payload")

    if candidate.startswith("```"):
        lines = [line for line in candidate.splitlines() if not line.strip().startswith("```")]
        candidate = "\n".join(lines).strip()

    payload: dict[str, Any] | None = None
    for fragment in (candidate, _extract_json_block(candidate)):
        if not fragment:
            continue
        try:
            parsed = json.loads(fragment)
            if isinstance(parsed, dict):
                payload = parsed
                break
        except json.JSONDecodeError:
            continue

    if payload is None:
        raise ValueError("invalid model payload")

    if isinstance(payload.get("data"), dict):
        payload = payload["data"]
    if isinstance(payload.get("result"), dict):
        payload = payload["result"]
    return payload


def _extract_json_block(text: str) -> str:
    match = _JSON_BLOCK_RE.search(text)
    return match.group(0) if match else ""


def _clamp(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(1.0, parsed))


def _build_detection_reply(report: BatchSkillReviewReport) -> str:
    summary = report.summary
    if summary.total_items <= 0:
        return (
            "已识别为检测任务并调用对应 skill。"
            f"本次共处理 {report.source_count} 份输入，暂未解析出有效检测项。"
        )
    return (
        "已识别为检测任务并调用对应 skill。"
        f"共处理 {report.source_count} 份输入，检测项 {summary.total_items} 条，"
        f"风险 {summary.risk_count} 条，通过 {summary.no_risk_count} 条。"
    )
