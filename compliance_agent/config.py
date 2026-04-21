from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping

from compliance_agent import __version__ as _PACKAGE_VERSION

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_OPENAI_BASE_URL = "https://api.deepseek.com"
DEFAULT_WORKFLOW_BASE_URL = "http://js2.blockelite.cn:23280/v1"


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_text(value: Any, default: str = "") -> str:
    if value is None:
        return default

    normalized = str(value).strip()
    if not normalized:
        return default
    return normalized


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_csv_tuple(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, (list, tuple, set)):
        parts = tuple(str(piece).strip() for piece in value if str(piece).strip())
        return parts or default

    parts = tuple(piece.strip() for piece in str(value).split(",") if piece.strip())
    return parts or default


@dataclass
class Settings:
    app_version: str = _PACKAGE_VERSION
    app_build: str = ""
    model: str = DEFAULT_MODEL
    material_classification_model: str = DEFAULT_MODEL
    material_classification_review_model: str = DEFAULT_MODEL
    material_classification_low_confidence_threshold: float = 0.78
    material_classification_small_review_threshold: float = 0.82
    material_classification_direct_big_min_parse_confidence: float = 0.45
    material_classification_direct_big_parsers: tuple[str, ...] = ("pdf_ocr", "image_ocr")
    material_classification_review_on_hint_conflict: bool = True
    material_classification_review_on_ambiguous_types: bool = True
    material_classification_max_text_chars: int = 6000
    material_classification_preview_pages: int = 1
    material_classification_cache_db_path: str = ".data/material_classification_cache.sqlite3"
    material_classification_prompt_version: str = "material-classification-v2"
    openai_base_url: str = DEFAULT_OPENAI_BASE_URL
    system_prompt: str = "You are a concise compliance assistant."
    openai_api_key: str = ""
    workflow_base_url: str = DEFAULT_WORKFLOW_BASE_URL
    contract_api_key: str = ""
    general_api_key: str = ""
    handbook_api_key: str = ""
    workflow_timeout_seconds: int = 30
    workflow_max_retries: int = 2
    enable_local_fallback: bool = False
    enable_streaming_report_items: bool = True
    enable_llm_report_analysis: bool = False
    parse_min_confidence: float = 0.45
    parse_min_chars: int = 80
    hitl_confidence_threshold: float = 0.55
    hitl_high_risk_threshold: int = 1
    artifact_store_enabled: bool = True
    artifact_store_dir: str = ""
    artifact_store_markdown: bool = True
    enable_graph: bool = False
    conversation_db_path: str = ".data/conversation_memory.sqlite3"
    conversation_context_messages: int = 16
    conversation_context_chars: int = 12000

    def update_from_mapping(self, mapping: Mapping[str, Any]) -> None:
        valid_fields = {field.name for field in fields(self)}
        for key, value in mapping.items():
            if key in valid_fields:
                setattr(self, key, value)

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


def build_settings_from_env(env: Mapping[str, Any] | None = None) -> Settings:
    source = env or os.environ

    model = _as_text(source.get("MODEL"), DEFAULT_MODEL)
    classification_model = _as_text(source.get("MATERIAL_CLASSIFICATION_MODEL"), model)
    review_model = _as_text(source.get("MATERIAL_CLASSIFICATION_REVIEW_MODEL"), classification_model)

    return Settings(
        app_version=_as_text(source.get("APP_VERSION"), _PACKAGE_VERSION),
        app_build=_as_text(source.get("APP_BUILD"), ""),
        model=model,
        material_classification_model=classification_model,
        material_classification_review_model=review_model,
        material_classification_low_confidence_threshold=_as_float(
            source.get("MATERIAL_CLASSIFICATION_LOW_CONFIDENCE_THRESHOLD"),
            0.78,
        ),
        material_classification_small_review_threshold=_as_float(
            source.get("MATERIAL_CLASSIFICATION_SMALL_REVIEW_THRESHOLD"),
            0.82,
        ),
        material_classification_direct_big_min_parse_confidence=_as_float(
            source.get("MATERIAL_CLASSIFICATION_DIRECT_BIG_MIN_PARSE_CONFIDENCE"),
            0.45,
        ),
        material_classification_direct_big_parsers=_as_csv_tuple(
            source.get("MATERIAL_CLASSIFICATION_DIRECT_BIG_PARSERS"),
            ("pdf_ocr", "image_ocr"),
        ),
        material_classification_review_on_hint_conflict=_as_bool(
            source.get("MATERIAL_CLASSIFICATION_REVIEW_ON_HINT_CONFLICT"),
            True,
        ),
        material_classification_review_on_ambiguous_types=_as_bool(
            source.get("MATERIAL_CLASSIFICATION_REVIEW_ON_AMBIGUOUS_TYPES"),
            True,
        ),
        material_classification_max_text_chars=_as_int(
            source.get("MATERIAL_CLASSIFICATION_MAX_TEXT_CHARS"),
            6000,
        ),
        material_classification_preview_pages=_as_int(
            source.get("MATERIAL_CLASSIFICATION_PREVIEW_PAGES"),
            1,
        ),
        material_classification_cache_db_path=_as_text(
            source.get("MATERIAL_CLASSIFICATION_CACHE_DB_PATH"),
            ".data/material_classification_cache.sqlite3",
        ),
        material_classification_prompt_version=_as_text(
            source.get("MATERIAL_CLASSIFICATION_PROMPT_VERSION"),
            "material-classification-v2",
        ),
        openai_base_url=_as_text(
            source.get("OPENAI_BASE_URL"),
            _as_text(source.get("DEEPSEEK_BASE_URL"), DEFAULT_OPENAI_BASE_URL),
        ),
        system_prompt=_as_text(
            source.get("SYSTEM_PROMPT"),
            "You are a concise compliance assistant.",
        ),
        openai_api_key=_as_text(source.get("OPENAI_API_KEY"), ""),
        workflow_base_url=_as_text(source.get("WORKFLOW_BASE_URL"), DEFAULT_WORKFLOW_BASE_URL),
        contract_api_key=_as_text(source.get("CONTRACT_API_KEY"), ""),
        general_api_key=_as_text(source.get("GENERAL_API_KEY"), ""),
        handbook_api_key=_as_text(source.get("HANDBOOK_API_KEY"), ""),
        workflow_timeout_seconds=_as_int(source.get("WORKFLOW_TIMEOUT_SECONDS"), 30),
        workflow_max_retries=_as_int(source.get("WORKFLOW_MAX_RETRIES"), 2),
        enable_local_fallback=_as_bool(source.get("ENABLE_LOCAL_FALLBACK"), False),
        enable_streaming_report_items=_as_bool(source.get("ENABLE_STREAMING_REPORT_ITEMS"), True),
        enable_llm_report_analysis=_as_bool(source.get("ENABLE_LLM_REPORT_ANALYSIS"), False),
        parse_min_confidence=_as_float(source.get("PARSE_MIN_CONFIDENCE"), 0.45),
        parse_min_chars=_as_int(source.get("PARSE_MIN_CHARS"), 80),
        hitl_confidence_threshold=_as_float(source.get("HITL_CONFIDENCE_THRESHOLD"), 0.55),
        hitl_high_risk_threshold=_as_int(source.get("HITL_HIGH_RISK_THRESHOLD"), 1),
        artifact_store_enabled=_as_bool(source.get("ARTIFACT_STORE_ENABLED"), True),
        artifact_store_dir=_as_text(source.get("ARTIFACT_STORE_DIR"), ""),
        artifact_store_markdown=_as_bool(source.get("ARTIFACT_STORE_MARKDOWN"), True),
        enable_graph=_as_bool(source.get("ENABLE_GRAPH"), False),
        conversation_db_path=_as_text(
            source.get("CONVERSATION_DB_PATH"),
            ".data/conversation_memory.sqlite3",
        ),
        conversation_context_messages=_as_int(source.get("CONVERSATION_CONTEXT_MESSAGES"), 16),
        conversation_context_chars=_as_int(source.get("CONVERSATION_CONTEXT_CHARS"), 12000),
    )


settings = build_settings_from_env()


def apply_settings(overrides: Mapping[str, Any] | None = None) -> Settings:
    if overrides:
        settings.update_from_mapping(overrides)
    return settings
