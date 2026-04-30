from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import httpx

from compliance_agent.models.schemas import ComplianceRequest, MaterialType, normalize_material_type
from compliance_agent.skills.registry import AUTO_CLASSIFICATION_MATERIAL_TYPE_OPTIONS, get_material_skill_spec

_CLASSIFICATION_QUERY = (
    "请根据输入材料判断其物料类型，并在合同场景补充参数。"
    "只输出JSON，不要Markdown。"
    f"字段: material_type({AUTO_CLASSIFICATION_MATERIAL_TYPE_OPTIONS}), "
    "contract_type, statement(甲方/乙方), scale(强势/均势), confidence(0-1), reason。"
)


class ExternalWorkflowClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 30,
        max_retries: int = 2,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.max_retries = max(0, max_retries)
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_seconds, transport=transport)

    def close(self) -> None:
        self._client.close()

    def upload_file(self, path: Path, user: str, api_key: str) -> str:
        if not path.exists():
            raise ValueError(f"File not found for upload: {path}")

        with path.open("rb") as fh:
            response = self._request(
                method="POST",
                endpoint="/files/upload",
                api_key=api_key,
                allow_retry=False,
                data={"user": user},
                files={"file": (path.name, fh)},
            )

        payload = response.json()
        upload_id = payload.get("id") or payload.get("upload_file_id")
        if not upload_id and isinstance(payload.get("data"), dict):
            upload_id = payload["data"].get("id")

        if not upload_id:
            raise ValueError("External upload response missing file id")

        return str(upload_id)

    def run_contract_workflow(self, req: ComplianceRequest, upload_file_id: str, api_key: str) -> str:
        payload = build_contract_payload(req, upload_file_id)
        response = self._request("POST", "/chat-messages", api_key=api_key, allow_retry=False, json=payload)
        return _extract_answer(response)

    def stream_contract_workflow(
        self,
        req: ComplianceRequest,
        upload_file_id: str,
        api_key: str,
    ) -> Iterator[str]:
        payload = build_contract_payload(req, upload_file_id)
        yield from self._stream_workflow_answer(payload=payload, api_key=api_key)

    def run_general_workflow(self, req: ComplianceRequest, upload_file_id: str, api_key: str) -> str:
        payload = build_general_payload(req, upload_file_id)
        response = self._request("POST", "/chat-messages", api_key=api_key, allow_retry=False, json=payload)
        return _extract_answer(response)

    def stream_general_workflow(
        self,
        req: ComplianceRequest,
        upload_file_id: str,
        api_key: str,
    ) -> Iterator[str]:
        payload = build_general_payload(req, upload_file_id)
        yield from self._stream_workflow_answer(payload=payload, api_key=api_key)

    def run_material_classification_workflow(
        self,
        user: str,
        upload_file_id: str,
        api_key: str,
        hint_material_type: str = "",
        input_type: str = "document",
    ) -> str:
        payload = build_material_classification_payload(
            user=user,
            upload_file_id=upload_file_id,
            hint_material_type=hint_material_type,
            input_type=input_type,
        )
        response = self._request("POST", "/chat-messages", api_key=api_key, allow_retry=False, json=payload)
        return _extract_answer(response)

    def run_chat_completions(
        self,
        messages: list[dict[str, Any]],
        api_key: str,
        model: str,
        response_format: dict[str, str] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        payload = build_chat_completion_payload(
            model=model,
            messages=messages,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        response = self._request("POST", "/chat/completions", api_key=api_key, allow_retry=True, json=payload)
        return _extract_chat_completion_content(response)

    def stream_chat_completions(
        self,
        messages: list[dict[str, Any]],
        api_key: str,
        model: str,
        response_format: dict[str, str] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        payload = build_chat_completion_payload(
            model=model,
            messages=messages,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        yield from self._stream_chat_completion_content(payload=payload, api_key=api_key)

    def _request(
        self,
        method: str,
        endpoint: str,
        api_key: str,
        allow_retry: bool = False,
        **kwargs,
    ) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {api_key}"

        max_retries = self.max_retries if allow_retry else 0
        attempt = 0
        while True:
            try:
                response = self._client.request(method, endpoint, headers=headers, **kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500 and attempt < max_retries:
                    attempt += 1
                    continue
                raise
            except httpx.HTTPError:
                if attempt < max_retries:
                    attempt += 1
                    continue
                raise

    def _stream_workflow_answer(
        self,
        *,
        payload: dict[str, Any],
        api_key: str,
    ) -> Iterator[str]:
        accumulated = ""
        for parsed in self._iter_stream_payloads(
            method="POST",
            endpoint="/chat-messages",
            api_key=api_key,
            json=payload,
        ):
            answer = _extract_answer_from_payload(parsed)
            if not answer:
                continue
            delta, accumulated = _normalize_stream_delta(answer, accumulated)
            if delta:
                yield delta

    def _stream_chat_completion_content(
        self,
        *,
        payload: dict[str, Any],
        api_key: str,
    ) -> Iterator[str]:
        for parsed in self._iter_stream_payloads(
            method="POST",
            endpoint="/chat/completions",
            api_key=api_key,
            json=payload,
        ):
            delta = _extract_chat_completion_delta(parsed)
            if delta:
                yield delta

    def _iter_stream_payloads(
        self,
        *,
        method: str,
        endpoint: str,
        api_key: str,
        **kwargs,
    ) -> Iterator[dict[str, Any]]:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {api_key}"

        with self._client.stream(method, endpoint, headers=headers, **kwargs) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line is None:
                    continue
                parsed = _parse_stream_payload_line(line)
                if parsed is not None:
                    yield parsed


def build_contract_payload(req: ComplianceRequest, upload_file_id: str) -> dict:
    json_rules = json.dumps(
        [item.model_dump(mode="json") for item in req.json_rules],
        ensure_ascii=False,
    )
    input_type = "document"
    if req.input_file and req.input_file.type in {"document", "image"}:
        input_type = req.input_file.type

    return {
        "inputs": {
            "f": {
                "type": input_type,
                "transfer_method": "local_file",
                "upload_file_id": upload_file_id,
            },
            "type": req.contract_type or "通用",
            "statement": req.statement or "甲方",
            "scale": req.scale or "均势",
            "json_rules": json_rules,
        },
        "query": req.query or "请执行合同合规审查",
        "response_mode": "streaming",
        "conversation_id": "",
        "user": req.user,
    }


def build_general_payload(req: ComplianceRequest, upload_file_id: str) -> dict:
    input_type = "document"
    if req.input_file and req.input_file.type in {"document", "image"}:
        input_type = req.input_file.type

    return {
        "inputs": {
            "input_file": {
                "type": input_type,
                "transfer_method": "local_file",
                "upload_file_id": upload_file_id,
            },
            "material_type": to_external_material_type(req.material_type),
        },
        "query": req.query or "请执行合规审查",
        "response_mode": "streaming",
        "conversation_id": "",
        "user": req.user,
    }


def build_material_classification_payload(
    user: str,
    upload_file_id: str,
    hint_material_type: str = "",
    input_type: str = "document",
) -> dict:
    return {
        "inputs": {
            "input_file": {
                "type": input_type,
                "transfer_method": "local_file",
                "upload_file_id": upload_file_id,
            },
            "hint_material_type": hint_material_type,
        },
        "query": _CLASSIFICATION_QUERY,
        "response_mode": "streaming",
        "conversation_id": "",
        "user": user,
    }


def build_chat_completion_payload(
    model: str,
    messages: list[dict[str, Any]],
    response_format: dict[str, str] | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": normalize_chat_model(model),
        "messages": messages,
        "stream": stream,
        "temperature": temperature,
    }
    if response_format is not None:
        payload["response_format"] = response_format
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    return payload


def to_external_material_type(material_type: MaterialType | str) -> str:
    normalized = normalize_material_type(material_type)
    if normalized is None:
        return "其它"

    spec = get_material_skill_spec(normalized)
    if spec is None:
        return "其它"
    return spec.external_material_type


def normalize_chat_model(model: str) -> str:
    value = (model or "").strip()
    if ":" in value:
        _, candidate = value.split(":", 1)
        if candidate.strip():
            return candidate.strip()
    return value or "deepseek-chat"


def _extract_answer(response: httpx.Response) -> str:
    payload: dict[str, Any] | None = None
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            payload = parsed
    except ValueError:
        payload = None

    if payload is not None:
        answer = _extract_answer_from_payload(payload)
        if answer:
            return answer

    stream_answer = _collect_answer_from_stream(response.text or "")
    if stream_answer:
        return stream_answer

    raise ValueError("External workflow response missing answer field")


def _extract_answer_from_payload(payload: dict[str, Any]) -> str:
    answer = payload.get("answer")
    if isinstance(answer, str) and answer.strip():
        return answer.strip()

    if isinstance(payload.get("data"), dict):
        candidate = payload["data"].get("answer")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        outputs = payload["data"].get("outputs")
        if isinstance(outputs, dict):
            candidate = outputs.get("answer")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

    return ""


def _collect_answer_from_stream(raw: str) -> str:
    parts: list[str] = []
    for line in raw.splitlines():
        parsed = _parse_stream_payload_line(line)
        if parsed is None:
            continue
        answer = _extract_answer_from_payload(parsed)
        if answer:
            parts.append(answer)

    if parts:
        return "".join(parts).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if isinstance(parsed, dict):
        return _extract_answer_from_payload(parsed)
    return ""


def _extract_chat_completion_content(response: httpx.Response) -> str:
    payload = response.json()
    content = _extract_chat_completion_content_from_payload(payload)
    if content:
        return content
    raise ValueError("Chat completion response missing content")


def _extract_chat_completion_content_from_payload(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    message = choices[0].get("message")
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        joined = "\n".join(parts).strip()
        if joined:
            return joined

    return ""


def _extract_chat_completion_delta(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return _extract_chat_completion_content_from_payload(payload)

    choice = choices[0]
    if not isinstance(choice, dict):
        return ""

    delta = choice.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str) and content:
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
            return "".join(parts)

    return _extract_chat_completion_content_from_payload(payload)


def _parse_stream_payload_line(raw_line: str) -> dict[str, Any] | None:
    payload_line = str(raw_line or "").strip()
    if not payload_line:
        return None
    if payload_line.startswith("event:"):
        return None
    if payload_line.startswith("data:"):
        payload_line = payload_line[len("data:") :].strip()
    if not payload_line or payload_line == "[DONE]":
        return None
    if not payload_line.startswith("{"):
        return None
    try:
        parsed = json.loads(payload_line)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _normalize_stream_delta(answer: str, accumulated: str) -> tuple[str, str]:
    text = str(answer or "")
    if not text:
        return "", accumulated

    if accumulated and text.startswith(accumulated):
        return text[len(accumulated) :], text

    if accumulated.endswith(text):
        return "", accumulated

    return text, accumulated + text
