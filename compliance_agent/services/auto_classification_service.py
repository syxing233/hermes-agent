from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from agent.auxiliary_client import call_llm, extract_content_or_reasoning
from compliance_agent.config import settings
from compliance_agent.hermes.runtime_config import ClassificationPolicy, WorkflowCredentialSet
from compliance_agent.models.schemas import ComplianceRequest, MaterialType, UploadFile, normalize_material_type
from compliance_agent.skills.registry import AUTO_CLASSIFICATION_MATERIAL_TYPE_OPTIONS
from compliance_agent.services.document_service import parse_document_with_quality, shutil_which
from compliance_agent.services.external_workflow_client import ExternalWorkflowClient
from hermes_cli.task_runtime import TaskProviderRuntime

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.S)
_MIN_REASON_CHARS = 8
_DIRECT_BIG_MIN_TEXT_CHARS = 120
_DEFAULT_PRIMARY_MODEL = "deepseek-chat"
_DEFAULT_PROMPT_VERSION = "material-classification-v2"
_DEFAULT_SMALL_REVIEW_THRESHOLD = 0.82
_DEFAULT_DIRECT_BIG_MIN_PARSE_CONFIDENCE = 0.45
_ALLOWED_TYPES = (
    MaterialType.CLAUSE_BOOK,
    MaterialType.POSTER,
    MaterialType.MARKETING,
    MaterialType.CONTRACT,
    MaterialType.HANDBOOK,
)
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
_PARSER_ALIASES = {
    "image_ocr": "image_tesseract",
}
_AMBIGUOUS_TYPE_PAIR_LABELS = {
    frozenset({MaterialType.CLAUSE_BOOK, MaterialType.HANDBOOK}): "条款书/产品说明书",
    frozenset({MaterialType.POSTER, MaterialType.MARKETING}): "海报/营销物料",
    frozenset({MaterialType.CONTRACT, MaterialType.CLAUSE_BOOK}): "合同/条款书",
}
_HANDBOOK_MARKERS = ("仅供理解参考", "以保险条款为准", "产品说明书", "投保说明", "重要提示")
_CLAUSE_BOOK_MARKERS = ("保险责任", "责任免除", "保险金申请", "合同解除", "争议处理", "释义")
_CONTRACT_MARKERS = ("甲方", "乙方", "本合同", "签署", "违约责任", "争议解决", "结算方式", "签章", "盖章")

_CLASSIFICATION_RULES = """\
你是保险合规材料分类助手。你必须从以下五类中强制选择最匹配的一类，不允许输出“其它”或“未知”。

分类标准：
1. 条款书：
如果文件的核心目的是正式约定保险合同的保障范围、责任边界和权利义务，正文通常以“保险责任、责任免除、释义、合同成立与生效、保险金申请、合同解除、争议处理”等条款化表达为主，语言严谨、规范、完整，并且文件本身就是最终适用依据，而不是“供理解参考”的解读材料，则判定为条款书。
2. 海报：
如果文件主要面向宣传展示，通常是单页或长图，图片和视觉元素占比高，文字较少，常用大标题、短口号、卖点、活动信息、二维码或联系方式来快速吸引注意，重点在传播触达而不是完整说明产品规则或形成法律约束，则判定为海报。
3. 营销物料：
如果文件主要用于产品推广、销售辅助或客户触达，内容围绕产品亮点、保障优势、适用人群、购买理由、方案推荐、活动宣传、销售话术、案例展示等展开，具有明显营销转化导向，虽然可能包含部分产品说明或条款摘要，但重点不在正式定义合同规则，也不在形成法律协议，则判定为营销物料。
4. 合同：
如果文件的核心作用是确认双方或多方之间的法律关系和约束，通常包含签约主体、权利义务、服务或合作内容、费用与结算、期限、违约责任、保密、争议解决、签字盖章等内容，语言具有明确法律约束性，目的在于达成正式协议而不是解释保险产品，则判定为合同。
5. 说明书：
如果文件属于保险产品说明书、投保说明书或类似解读性规范文件，核心作用是帮助用户理解产品、条款或投保事项，通常会包含“重要提示、产品特色、投保范围、保障责任、责任免除、保费说明、犹豫期、示例演示”等模块，并常明确说明“仅供理解参考，以保险条款或正式合同约定为准”，即它是对条款的说明和辅助解读，而非条款原文本身，则判定为说明书。你上传的样例就符合这一类。

强区分要求：
- “条款书”和“说明书”的首要区别是：条款书是最终适用依据；说明书是解释或辅助理解材料。
- “海报”和“营销物料”的首要区别是：海报以视觉展示和单页传播为主；营销物料以销售转化内容为主。
- “合同”和保险类材料的首要区别是：合同用于确认多方权利义务和法律关系。
- 如果输入里提供了 hint_material_type，它只作为弱提示；一旦与正文、版式预览或图片内容冲突，必须以后者为准。

输出要求：
- 只输出 JSON 对象，不要 Markdown，不要额外解释。
- 字段固定为：material_type({material_types}), contract_type, statement(甲方/乙方), scale(强势/均势), confidence(0-1), reason。
- reason 必须写清楚为什么判这个类别，至少 8 个字。
- 如果不是合同，contract_type / statement / scale 置为空字符串。
- 判定为说明书时，material_type 输出“产品说明书”。
- 即使信息不完整，也必须在五类中选一个最可能的结果。
"""

_REVIEW_APPENDIX = """\
你正在做二次复核。请基于原始材料摘要、预览图和第一次判断结果重新裁决。
如果第一次判断置信度偏低、理由过短、字段不完整或分类不稳，请直接覆盖为你认为最合理的最终分类。
仍然必须输出五类之一，不能输出“其它”。
"""


@dataclass(frozen=True)
class AutoClassification:
    material_type: MaterialType
    confidence: float
    source: str
    reason: str = ""
    contract_type: str | None = None
    statement: str | None = None
    scale: str | None = None
    model_stage: str = ""
    route: str = ""
    parser: str = ""
    parse_confidence: float = 0.0
    hint_conflict: bool = False
    ambiguous_pair: str = ""
    escalated_to_big: bool = False
    decision_reasons: tuple[str, ...] = ()
    review_attempted: bool = False


class MaterialClassificationError(ValueError):
    pass


@dataclass(frozen=True)
class _PreviewAsset:
    data_url: str
    digest: str


@dataclass(frozen=True)
class _SourceBundle:
    source_name: str
    source_path: str | None
    file_extension: str
    hint_material_type: str
    source_text_excerpt: str
    source_text_char_count: int
    text_excerpt: str
    context_excerpt: str
    parser: str
    parse_confidence: float
    warnings: tuple[str, ...]
    preview_assets: tuple[_PreviewAsset, ...]


@dataclass(frozen=True)
class _ModelAttempt:
    result: AutoClassification | None
    raw_answer: str = ""
    error: str = ""
    validation_issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class _RoutingDecision:
    route: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ReviewDecision:
    should_review: bool
    reasons: tuple[str, ...] = ()
    hint_conflict: bool = False
    ambiguous_pair: str = ""


class MaterialClassificationService:
    def __init__(
        self,
        client: ExternalWorkflowClient | None = None,
        workflow_credentials: WorkflowCredentialSet | None = None,
        classification_model: str | None = None,
        review_model: str | None = None,
        primary_model_runtime: TaskProviderRuntime | None = None,
        review_model_runtime: TaskProviderRuntime | None = None,
        classification_policy: ClassificationPolicy | None = None,
        low_confidence_threshold: float | None = None,
        max_text_chars: int | None = None,
        preview_pages: int | None = None,
        cache_db_path: str | None = None,
        prompt_version: str | None = None,
    ):
        self.workflow_client = client
        self.workflow_credentials = workflow_credentials
        policy = classification_policy or ClassificationPolicy(
            low_confidence_threshold=float(
                low_confidence_threshold
                if low_confidence_threshold is not None
                else getattr(settings, "material_classification_low_confidence_threshold", 0.78)
            ),
            small_review_threshold=float(
                getattr(
                    settings,
                    "material_classification_small_review_threshold",
                    low_confidence_threshold if low_confidence_threshold is not None else _DEFAULT_SMALL_REVIEW_THRESHOLD,
                )
            ),
            direct_big_min_parse_confidence=float(
                getattr(
                    settings,
                    "material_classification_direct_big_min_parse_confidence",
                    _DEFAULT_DIRECT_BIG_MIN_PARSE_CONFIDENCE,
                )
            ),
            direct_big_parsers=tuple(
                getattr(settings, "material_classification_direct_big_parsers", ("pdf_ocr", "image_ocr"))
            ),
            review_on_hint_conflict=bool(
                getattr(settings, "material_classification_review_on_hint_conflict", True)
            ),
            review_on_ambiguous_types=bool(
                getattr(settings, "material_classification_review_on_ambiguous_types", True)
            ),
            max_text_chars=int(
                max_text_chars
                if max_text_chars is not None
                else getattr(settings, "material_classification_max_text_chars", 6000)
            ),
            preview_pages=int(
                preview_pages
                if preview_pages is not None
                else getattr(settings, "material_classification_preview_pages", 1)
            ),
            cache_db_path=str(
                cache_db_path
                if cache_db_path is not None
                else getattr(settings, "material_classification_cache_db_path", "")
            ),
            prompt_version=(
                prompt_version
                or getattr(settings, "material_classification_prompt_version", "")
                or _DEFAULT_PROMPT_VERSION
            ),
            request_timeout_seconds=float(getattr(settings, "workflow_timeout_seconds", 30)),
        )

        classification_model = (
            classification_model
            or getattr(settings, "material_classification_model", "")
            or getattr(settings, "model", "")
            or _DEFAULT_PRIMARY_MODEL
        )
        review_model = (
            review_model
            or getattr(settings, "material_classification_review_model", "")
            or classification_model
        )
        self.primary_model_runtime = primary_model_runtime or TaskProviderRuntime(
            configured_provider="custom",
            resolved_provider="custom",
            model=classification_model,
            api_mode="chat_completions",
            base_url=(getattr(settings, "openai_base_url", "") or getattr(settings, "workflow_base_url", "")),
            api_key=getattr(settings, "openai_api_key", ""),
            source="legacy-standalone",
            requested_provider="custom",
        )
        self.review_model_runtime = review_model_runtime or TaskProviderRuntime(
            configured_provider=self.primary_model_runtime.configured_provider,
            resolved_provider=self.primary_model_runtime.resolved_provider,
            model=review_model,
            api_mode=self.primary_model_runtime.api_mode,
            base_url=self.primary_model_runtime.base_url,
            api_key=self.primary_model_runtime.api_key,
            source=self.primary_model_runtime.source,
            requested_provider=self.primary_model_runtime.requested_provider,
        )
        self.classification_model = self.primary_model_runtime.model
        self.review_model = self.review_model_runtime.model
        self.low_confidence_threshold = max(
            0.0,
            min(
                1.0,
                float(
                    policy.low_confidence_threshold
                ),
            ),
        )
        self.small_review_threshold = max(
            0.0,
            min(
                1.0,
                float(
                    policy.small_review_threshold
                ),
            ),
        )
        self.low_confidence_threshold = self.small_review_threshold
        self.direct_big_min_parse_confidence = max(
            0.0,
            min(
                1.0,
                float(
                    policy.direct_big_min_parse_confidence
                ),
            ),
        )
        self.direct_big_parsers = frozenset(
            _normalize_parser_names(policy.direct_big_parsers)
        )
        self.review_on_hint_conflict = bool(policy.review_on_hint_conflict)
        self.review_on_ambiguous_types = bool(policy.review_on_ambiguous_types)
        self.max_text_chars = max(
            1200,
            int(
                max_text_chars
                if max_text_chars is not None
                else policy.max_text_chars
            ),
        )
        self.preview_pages = max(
            1,
            int(
                preview_pages
                if preview_pages is not None
                else policy.preview_pages
            ),
        )
        self.cache_db_path = str(
            cache_db_path
            if cache_db_path is not None
            else policy.cache_db_path
        )
        self.prompt_version = (
            prompt_version
            or policy.prompt_version
            or _DEFAULT_PROMPT_VERSION
        )
        self.request_timeout_seconds = max(1.0, float(policy.request_timeout_seconds))

    def classify(
        self,
        user: str,
        source_name: str,
        input_text: str | None = None,
        local_path: str | None = None,
        hint_material_type: MaterialType | str | None = None,
    ) -> AutoClassification:
        normalized_hint = _parse_material_type(hint_material_type)

        is_image = (
            local_path is not None
            and Path(local_path).suffix.lower() in _IMAGE_SUFFIXES
        )
        if is_image:
            hint_text = normalized_hint.value if normalized_hint is not None else ""
            external_result = self._classify_image_via_external_workflow(
                user=user,
                local_path=local_path,
                hint_material_type=hint_text,
            )
            if external_result is not None:
                return external_result

        source = self._build_source_bundle(
            source_name=source_name,
            input_text=input_text,
            local_path=local_path,
            hint_material_type=normalized_hint,
        )

        route = self._route_source(source)
        if route.route == "direct_big":
            direct_big = self._call_model(
                runtime=self.review_model_runtime,
                messages=build_material_classification_messages(
                    source=source,
                    prompt_version=self.prompt_version,
                ),
            )
            if direct_big.result is None:
                detail = direct_big.error or "模型未返回有效分类结果"
                raise MaterialClassificationError(f"自动分类失败: {detail}")
            final_result = replace(
                direct_big.result,
                source="model",
                model_stage="direct_big",
                route="direct_big",
                parser=source.parser,
                parse_confidence=source.parse_confidence,
                escalated_to_big=True,
                decision_reasons=route.reasons,
            )
            return final_result

        primary = self._call_model(
            runtime=self.primary_model_runtime,
            messages=build_material_classification_messages(
                source=source,
                prompt_version=self.prompt_version,
            ),
        )

        final_attempt = primary
        final_stage = "primary_small"
        review_attempt: _ModelAttempt | None = None
        review_decision = self._review_decision(source, primary)
        if review_decision.should_review:
            review_attempt = self._call_model(
                runtime=self.review_model_runtime,
                messages=build_material_classification_messages(
                    source=source,
                    prompt_version=self.prompt_version,
                    primary_attempt=primary,
                    review=True,
                ),
            )
            if review_attempt.result is not None:
                final_attempt = review_attempt
                final_stage = "review_big_after_small"

        if final_attempt.result is None:
            detail = "; ".join(
                piece
                for piece in (
                    primary.error,
                    "" if review_attempt is None else review_attempt.error,
                )
                if piece
            )
            if not detail:
                detail = "模型未返回有效分类结果"
            raise MaterialClassificationError(f"自动分类失败: {detail}")

        final_result = replace(
            final_attempt.result,
            source="model",
            model_stage=final_stage,
            route="small_first",
            parser=source.parser,
            parse_confidence=source.parse_confidence,
            hint_conflict=review_decision.hint_conflict,
            ambiguous_pair=review_decision.ambiguous_pair,
            escalated_to_big=review_attempt is not None,
            decision_reasons=review_decision.reasons,
            review_attempted=review_attempt is not None,
        )
        return final_result

    def _call_model(
        self,
        *,
        runtime: TaskProviderRuntime,
        messages: list[dict[str, Any]],
    ) -> _ModelAttempt:
        if not runtime.ready():
            return _ModelAttempt(
                result=None,
                error=(
                    "未解析到可用的分类模型凭证: "
                    f"compliance.classification provider={runtime.configured_provider}, "
                    f"model={runtime.model}"
                ),
            )
        try:
            explicit_base_url = None
            explicit_api_key = None
            requested_provider = runtime.requested_provider or runtime.configured_provider
            if requested_provider == "custom":
                explicit_base_url = runtime.base_url
                explicit_api_key = runtime.api_key
            response = call_llm(
                provider=requested_provider,
                model=runtime.model,
                base_url=explicit_base_url,
                api_key=explicit_api_key,
                messages=messages,
                temperature=0.0,
                max_tokens=1000,
                timeout=self.request_timeout_seconds,
            )
            answer = extract_content_or_reasoning(response)
        except Exception as exc:
            return _ModelAttempt(result=None, error=f"model_call_failed:{exc.__class__.__name__}")

        try:
            payload = _parse_model_payload(answer)
            result = _classification_from_payload(payload)
            return _ModelAttempt(
                result=result,
                raw_answer=answer,
                validation_issues=_validation_issues_from_payload(payload, result),
            )
        except Exception as exc:
            return _ModelAttempt(
                result=None,
                raw_answer=answer,
                error=f"invalid_model_payload:{exc.__class__.__name__}",
            )

    def _classify_image_via_external_workflow(
        self,
        *,
        user: str,
        local_path: str,
        hint_material_type: str,
    ) -> AutoClassification | None:
        if self.workflow_client is None:
            return None

        general_api_key = getattr(self.workflow_credentials, "general_api_key", "")
        if not general_api_key:
            return None

        try:
            upload_file_id = self.workflow_client.upload_file(
                path=Path(local_path),
                user=user,
                api_key=general_api_key,
            )
        except Exception:
            return None

        try:
            raw_answer = self.workflow_client.run_material_classification_workflow(
                user=user,
                upload_file_id=upload_file_id,
                api_key=general_api_key,
                hint_material_type=hint_material_type,
                input_type="image",
            )
        except Exception:
            return None

        try:
            payload = _parse_model_payload(raw_answer)
            result = _classification_from_payload(payload, allow_empty_reason=True)
        except Exception:
            return None

        return replace(
            result,
            source="external_workflow",
            model_stage="external_workflow",
            route="external_workflow_image",
            parser="image_external_workflow",
            parse_confidence=1.0,
        )

    def _route_source(self, source: _SourceBundle) -> _RoutingDecision:
        reasons: list[str] = []
        parser = _normalize_parser_name(source.parser)
        if parser in self.direct_big_parsers:
            reasons.append(f"parser:{parser}")
        if source.parse_confidence < self.direct_big_min_parse_confidence:
            reasons.append("low_parse_confidence")
        if source.source_text_char_count < _DIRECT_BIG_MIN_TEXT_CHARS and source.preview_assets:
            reasons.append("preview_reliant_short_text")
        if reasons:
            return _RoutingDecision(route="direct_big", reasons=tuple(_dedupe_preserve_order(reasons)))
        return _RoutingDecision(route="small_first")

    def _review_decision(self, source: _SourceBundle, attempt: _ModelAttempt) -> _ReviewDecision:
        reasons: list[str] = []
        hint_conflict = False
        ambiguous_pair = ""
        if attempt.result is None:
            if attempt.error.startswith("invalid_model_payload"):
                reasons.append("invalid_json")
            else:
                reasons.append("primary_failed")
            return _ReviewDecision(should_review=True, reasons=tuple(reasons))
        if attempt.result.confidence < self.small_review_threshold:
            reasons.append("low_confidence")
        reasons.extend(attempt.validation_issues)
        if self.review_on_hint_conflict and _is_hint_conflict(source.hint_material_type, attempt.result.material_type):
            hint_conflict = True
            reasons.append("hint_conflict")
        if self.review_on_ambiguous_types:
            ambiguous_pair = _detect_ambiguous_pair(source, attempt.result.material_type)
            if ambiguous_pair:
                reasons.append(f"ambiguous:{ambiguous_pair}")
        reasons = _dedupe_preserve_order(reasons)
        return _ReviewDecision(
            should_review=bool(reasons),
            reasons=tuple(reasons),
            hint_conflict=hint_conflict,
            ambiguous_pair=ambiguous_pair,
        )

    def _build_source_bundle(
        self,
        *,
        source_name: str,
        input_text: str | None,
        local_path: str | None,
        hint_material_type: MaterialType | str | None,
    ) -> _SourceBundle:
        normalized_text = (input_text or "").strip()
        normalized_hint = _parse_material_type(hint_material_type)
        hint_material_text = normalized_hint.value if normalized_hint is not None else ""
        parser = "inline_text"
        parse_confidence = 1.0 if normalized_text else 0.0
        warnings: list[str] = []
        path = Path(local_path) if local_path else None

        if not normalized_text and local_path:
            req = ComplianceRequest(
                user="classifier",
                material_type=MaterialType.OTHER,
                input_file=UploadFile(local_path=local_path),
            )
            extracted_text, _, quality = parse_document_with_quality(req)
            normalized_text = extracted_text.strip()
            parser = quality.parser
            parse_confidence = quality.parse_confidence
            warnings = list(quality.warnings)

        preview_assets = self._build_preview_assets(path) if path is not None else []
        if not normalized_text and not preview_assets:
            raise MaterialClassificationError("自动分类失败: 无法提取可用于分类的文本或预览信息。")

        source_text_excerpt = _clip_text(normalized_text, self.max_text_chars)

        source_path = str(path) if path is not None else None
        file_extension = path.suffix.lower() if path is not None else ""

        return _SourceBundle(
            source_name=source_name,
            source_path=source_path,
            file_extension=file_extension,
            hint_material_type=hint_material_text,
            source_text_excerpt=source_text_excerpt,
            source_text_char_count=len(normalized_text),
            text_excerpt=source_text_excerpt,
            context_excerpt="",
            parser=parser,
            parse_confidence=parse_confidence,
            warnings=tuple(warnings),
            preview_assets=tuple(preview_assets),
        )

    def _build_preview_assets(self, path: Path) -> list[_PreviewAsset]:
        suffix = path.suffix.lower()
        if suffix in _IMAGE_SUFFIXES:
            preview = _file_to_preview_asset(path)
            return [preview] if preview is not None else []
        if suffix == ".pdf":
            return _pdf_to_preview_assets(path, max_pages=self.preview_pages)
        return []

AutoClassificationService = MaterialClassificationService


def build_material_classification_messages(
    source: _SourceBundle,
    prompt_version: str,
    primary_attempt: _ModelAttempt | None = None,
    review: bool = False,
) -> list[dict[str, Any]]:
    system_prompt = (
        f"{getattr(settings, 'system_prompt', 'You are a concise compliance assistant.')}\n"
        + _CLASSIFICATION_RULES.format(material_types=AUTO_CLASSIFICATION_MATERIAL_TYPE_OPTIONS)
    )
    if review:
        system_prompt = f"{system_prompt}\n\n{_REVIEW_APPENDIX}"

    payload: dict[str, Any] = {
        "prompt_version": prompt_version,
        "source_name": source.source_name,
        "file_extension": source.file_extension,
        "source_path": source.source_path or "",
        "hint_material_type": source.hint_material_type,
        "parse": {
            "parser": source.parser,
            "parse_confidence": source.parse_confidence,
            "warnings": list(source.warnings),
        },
        "text_excerpt": source.text_excerpt,
        "context_excerpt": source.context_excerpt,
        "preview_count": len(source.preview_assets),
    }
    if review and primary_attempt is not None:
        payload["first_pass"] = {
            "raw_answer": primary_attempt.raw_answer,
            "error": primary_attempt.error,
            "parsed_result": (
                None
                if primary_attempt.result is None
                else {
                    "material_type": primary_attempt.result.material_type.value,
                    "confidence": primary_attempt.result.confidence,
                    "reason": primary_attempt.result.reason,
                    "contract_type": primary_attempt.result.contract_type or "",
                    "statement": primary_attempt.result.statement or "",
                    "scale": primary_attempt.result.scale or "",
                }
            ),
        }

    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": json.dumps(payload, ensure_ascii=False),
        }
    ]
    user_content.extend(
        {
            "type": "image_url",
            "image_url": {
                "url": asset.data_url,
            },
        }
        for asset in source.preview_assets
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def _classification_from_payload(payload: dict[str, Any], allow_empty_reason: bool = False) -> AutoClassification:
    material = _parse_material_type(payload.get("material_type"))
    if material is None:
        raise ValueError("material_type")

    confidence = _parse_confidence(payload.get("confidence"), fallback=0.51)
    reason = str(payload.get("reason") or "").strip()
    if not allow_empty_reason and len(reason) < _MIN_REASON_CHARS:
        raise ValueError("reason")

    if material != MaterialType.CONTRACT:
        return AutoClassification(
            material_type=material,
            confidence=confidence,
            source="model",
            reason=reason,
        )

    return AutoClassification(
        material_type=material,
        confidence=confidence,
        source="model",
        reason=reason,
        contract_type=_pick_contract_type(payload.get("contract_type")) or "通用",
        statement=_pick_statement(payload.get("statement")) or "甲方",
        scale=_pick_scale(payload.get("scale")) or "均势",
    )


def _parse_model_payload(answer: str) -> dict[str, Any]:
    candidate = (answer or "").strip()
    if not candidate:
        raise ValueError("empty classification answer")

    if candidate.startswith("```"):
        lines = [line for line in candidate.splitlines() if not line.strip().startswith("```")]
        candidate = "\n".join(lines).strip()

    payload: dict[str, Any] | None = None
    for raw in (candidate, _extract_json_block(candidate)):
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                payload = parsed
                break
        except json.JSONDecodeError:
            continue

    if payload is None:
        raise ValueError("classification answer is not valid JSON")

    if isinstance(payload.get("data"), dict):
        payload = payload["data"]
    if isinstance(payload.get("result"), dict):
        payload = payload["result"]
    return payload


def _extract_json_block(text: str) -> str:
    match = _JSON_BLOCK_RE.search(text)
    return match.group(0) if match else ""


def _merge_context_text(text: str, context_text: str | None) -> str:
    source_text = (text or "").strip()
    context = (context_text or "").strip()
    if not context:
        return source_text
    if not source_text:
        return context
    if context in source_text:
        return source_text
    return f"{source_text}\n\n补充上下文：\n{context}"


def _clip_text(text: str, limit: int) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    head_chars = int(limit * 0.7)
    tail_chars = max(200, limit - head_chars - 32)
    omitted = max(0, len(normalized) - head_chars - tail_chars)
    return (
        f"{normalized[:head_chars]}\n\n"
        f"...[中间省略 {omitted} 字]...\n\n"
        f"{normalized[-tail_chars:]}"
    )


def _parse_material_type(value: Any) -> MaterialType | None:
    normalized = normalize_material_type(value)
    if normalized in _ALLOWED_TYPES:
        return normalized

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
    if "营销" in text or "宣传" in text or "文案" in text:
        return MaterialType.MARKETING
    return None


def _parse_confidence(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(1.0, parsed))


def _pick_contract_type(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _pick_statement(value: Any) -> str | None:
    text = str(value or "").strip()
    if text in {"甲方", "乙方"}:
        return text
    return None


def _pick_scale(value: Any) -> str | None:
    text = str(value or "").strip()
    if text in {"强势", "均势"}:
        return text
    return None


def _validation_issues_from_payload(payload: dict[str, Any], result: AutoClassification) -> tuple[str, ...]:
    issues: list[str] = []
    if result.material_type == MaterialType.CONTRACT:
        if not _pick_contract_type(payload.get("contract_type")):
            issues.append("missing_contract_type")
        if not _pick_statement(payload.get("statement")):
            issues.append("missing_statement")
        if not _pick_scale(payload.get("scale")):
            issues.append("missing_scale")
    return tuple(issues)


def _is_hint_conflict(hint_material_type: str, material_type: MaterialType) -> bool:
    hint = _parse_material_type(hint_material_type)
    return hint is not None and hint != material_type


def _detect_ambiguous_pair(source: _SourceBundle, material_type: MaterialType) -> str:
    text = source.source_text_excerpt
    if not text:
        return ""
    if material_type in {MaterialType.CLAUSE_BOOK, MaterialType.HANDBOOK}:
        if material_type == MaterialType.CLAUSE_BOOK and _contains_any(text, _HANDBOOK_MARKERS):
            return _AMBIGUOUS_TYPE_PAIR_LABELS[frozenset({MaterialType.CLAUSE_BOOK, MaterialType.HANDBOOK})]
        if material_type == MaterialType.HANDBOOK and _contains_any(text, _CLAUSE_BOOK_MARKERS):
            return _AMBIGUOUS_TYPE_PAIR_LABELS[frozenset({MaterialType.CLAUSE_BOOK, MaterialType.HANDBOOK})]
    if material_type in {MaterialType.POSTER, MaterialType.MARKETING}:
        if material_type == MaterialType.POSTER and source.source_text_char_count >= _DIRECT_BIG_MIN_TEXT_CHARS:
            return _AMBIGUOUS_TYPE_PAIR_LABELS[frozenset({MaterialType.POSTER, MaterialType.MARKETING})]
        if material_type == MaterialType.MARKETING and source.preview_assets and source.source_text_char_count <= 160:
            return _AMBIGUOUS_TYPE_PAIR_LABELS[frozenset({MaterialType.POSTER, MaterialType.MARKETING})]
    if material_type in {MaterialType.CONTRACT, MaterialType.CLAUSE_BOOK}:
        if material_type == MaterialType.CONTRACT and _contains_any(text, _CLAUSE_BOOK_MARKERS):
            return _AMBIGUOUS_TYPE_PAIR_LABELS[frozenset({MaterialType.CONTRACT, MaterialType.CLAUSE_BOOK})]
        if material_type == MaterialType.CLAUSE_BOOK and _contains_any(text, _CONTRACT_MARKERS):
            return _AMBIGUOUS_TYPE_PAIR_LABELS[frozenset({MaterialType.CONTRACT, MaterialType.CLAUSE_BOOK})]
    return ""


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    normalized = (text or "").strip()
    return any(marker in normalized for marker in markers)


def _normalize_parser_name(value: str) -> str:
    parser = str(value or "").strip()
    return _PARSER_ALIASES.get(parser, parser)


def _normalize_parser_names(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_parts = value.split(",")
    elif isinstance(value, (list, tuple, set, frozenset)):
        raw_parts = list(value)
    else:
        raw_parts = [value]
    normalized = [
        _normalize_parser_name(str(part or "").strip())
        for part in raw_parts
        if str(part or "").strip()
    ]
    return tuple(_dedupe_preserve_order(normalized))


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _file_to_preview_asset(path: Path) -> _PreviewAsset | None:
    try:
        raw = path.read_bytes()
    except Exception:
        return None
    mime_type = _mime_type_for_suffix(path.suffix.lower())
    data_url = f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}"
    return _PreviewAsset(data_url=data_url, digest=hashlib.sha256(raw).hexdigest())


def _pdf_to_preview_assets(path: Path, max_pages: int) -> list[_PreviewAsset]:
    if not shutil_which("pdftoppm"):
        return []
    with tempfile.TemporaryDirectory(prefix="material_preview_") as tmp_dir:
        prefix = str(Path(tmp_dir) / "page")
        try:
            subprocess.check_call(
                ["pdftoppm", "-f", "1", "-l", str(max_pages), "-png", str(path), prefix],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return []
        previews: list[_PreviewAsset] = []
        for image_path in sorted(Path(tmp_dir).glob("page-*.png")):
            preview = _file_to_preview_asset(image_path)
            if preview is not None:
                previews.append(preview)
        return previews


def _mime_type_for_suffix(suffix: str) -> str:
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    if suffix in {".tif", ".tiff"}:
        return "image/tiff"
    return "image/png"
