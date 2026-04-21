from __future__ import annotations

from typing import Any

from compliance_agent.hermes.runtime_config import (
    ArtifactStoreConfig,
    ClassificationPolicy,
    ClassificationTaskConfig,
    ComplianceRuntimeOptions,
    EmbeddedComplianceConfig,
    HitlPolicy,
    ParsingPolicy,
    ResolvedComplianceRuntimeConfig,
    WorkflowCredentialSet,
    WorkflowSettings,
    settings_fingerprint,
)
from hermes_cli.config import load_config, load_env, read_raw_config
from hermes_cli.env_loader import load_hermes_dotenv
from hermes_cli.task_runtime import resolve_task_runtime

_LEGACY_COMPLIANCE_CONFIG_KEYS = (
    "workflow_base_url",
    "contract_api_key",
    "general_api_key",
    "handbook_api_key",
    "classification_model",
    "review_model",
    "enable_graph",
    "artifact_store_enabled",
    "artifact_store_dir",
    "artifact_store_markdown",
    "parse_min_confidence",
    "parse_min_chars",
    "hitl_confidence_threshold",
    "hitl_high_risk_threshold",
)

_LEGACY_COMPLIANCE_ENV_KEYS = (
    "WORKFLOW_BASE_URL",
    "CONTRACT_API_KEY",
    "GENERAL_API_KEY",
    "HANDBOOK_API_KEY",
    "COMPLIANCE_CLASSIFICATION_MODEL",
    "COMPLIANCE_REVIEW_MODEL",
    "MATERIAL_CLASSIFICATION_MODEL",
    "MATERIAL_CLASSIFICATION_REVIEW_MODEL",
)


def load_embedded_compliance_config() -> EmbeddedComplianceConfig:
    load_hermes_dotenv()
    project_env = load_env()
    env_values = _load_hermes_env(project_env)
    raw_config = read_raw_config()
    _assert_no_legacy_compliance_shape(raw_config, project_env)

    config = load_config()
    compliance_cfg = config.get("compliance") if isinstance(config, dict) else {}
    compliance_cfg = compliance_cfg if isinstance(compliance_cfg, dict) else {}

    workflow_cfg = _as_dict(compliance_cfg.get("workflow"))
    classification_cfg = _as_dict(compliance_cfg.get("classification"))
    primary_cfg = _as_dict(classification_cfg.get("primary"))
    review_cfg = _as_dict(classification_cfg.get("review"))
    policy_cfg = _as_dict(classification_cfg.get("policy"))
    parsing_cfg = _as_dict(compliance_cfg.get("parsing"))
    hitl_cfg = _as_dict(compliance_cfg.get("hitl"))
    artifacts_cfg = _as_dict(compliance_cfg.get("artifacts"))
    runtime_cfg = _as_dict(compliance_cfg.get("runtime"))

    return EmbeddedComplianceConfig(
        workflow=WorkflowSettings(
            base_url=_coalesce_text(workflow_cfg.get("base_url"), "http://js2.blockelite.cn:23280/v1"),
            timeout_seconds=_coalesce_int(workflow_cfg.get("timeout_seconds"), 30),
            max_retries=_coalesce_int(workflow_cfg.get("max_retries"), 2),
        ),
        classification_primary=ClassificationTaskConfig(
            provider=_coalesce_text(primary_cfg.get("provider"), "deepseek"),
            model=_coalesce_text(primary_cfg.get("model"), "deepseek-chat"),
        ),
        classification_review=ClassificationTaskConfig(
            provider=_coalesce_text(review_cfg.get("provider"), "deepseek"),
            model=_coalesce_text(review_cfg.get("model"), "deepseek-chat"),
        ),
        classification_policy=ClassificationPolicy(
            low_confidence_threshold=_coalesce_float(policy_cfg.get("low_confidence_threshold"), 0.78),
            small_review_threshold=_coalesce_float(policy_cfg.get("small_review_threshold"), 0.82),
            direct_big_min_parse_confidence=_coalesce_float(
                policy_cfg.get("direct_big_min_parse_confidence"),
                0.45,
            ),
            direct_big_parsers=_coalesce_tuple(policy_cfg.get("direct_big_parsers"), ("pdf_ocr", "image_ocr")),
            review_on_hint_conflict=_coalesce_bool(policy_cfg.get("review_on_hint_conflict"), True),
            review_on_ambiguous_types=_coalesce_bool(policy_cfg.get("review_on_ambiguous_types"), True),
            max_text_chars=max(1200, _coalesce_int(policy_cfg.get("max_text_chars"), 6000)),
            preview_pages=max(1, _coalesce_int(policy_cfg.get("preview_pages"), 1)),
            cache_db_path=_coalesce_text(
                policy_cfg.get("cache_db_path"),
                ".data/material_classification_cache.sqlite3",
            ),
            prompt_version=_coalesce_text(policy_cfg.get("prompt_version"), "material-classification-v2"),
            request_timeout_seconds=float(_coalesce_int(workflow_cfg.get("timeout_seconds"), 30)),
        ),
        parsing=ParsingPolicy(
            min_confidence=_coalesce_float(parsing_cfg.get("min_confidence"), 0.45),
            min_chars=_coalesce_int(parsing_cfg.get("min_chars"), 80),
        ),
        hitl=HitlPolicy(
            confidence_threshold=_coalesce_float(hitl_cfg.get("confidence_threshold"), 0.55),
            high_risk_threshold=_coalesce_int(hitl_cfg.get("high_risk_threshold"), 1),
        ),
        artifacts=ArtifactStoreConfig(
            enabled=_coalesce_bool(artifacts_cfg.get("enabled"), True),
            dir=_coalesce_text(artifacts_cfg.get("dir"), ""),
            markdown=_coalesce_bool(artifacts_cfg.get("markdown"), True),
        ),
        runtime=ComplianceRuntimeOptions(
            enable_graph=_coalesce_bool(runtime_cfg.get("enable_graph"), False),
            stream_report_items=True,
        ),
    )


def load_compliance_settings() -> ResolvedComplianceRuntimeConfig:
    embedded = load_embedded_compliance_config()
    env_values = _load_hermes_env()

    workflow_credentials = WorkflowCredentialSet(
        contract_api_key=_coalesce_text(env_values.get("COMPLIANCE_CONTRACT_API_KEY"), ""),
        general_api_key=_coalesce_text(env_values.get("COMPLIANCE_GENERAL_API_KEY"), ""),
        handbook_api_key=_coalesce_text(env_values.get("COMPLIANCE_HANDBOOK_API_KEY"), ""),
    )

    return ResolvedComplianceRuntimeConfig(
        app_version=embedded.app_version,
        app_build=embedded.app_build,
        workflow=embedded.workflow,
        workflow_credentials=workflow_credentials,
        classification_primary=resolve_task_runtime(
            provider=embedded.classification_primary.provider,
            model=embedded.classification_primary.model,
        ),
        classification_review=resolve_task_runtime(
            provider=embedded.classification_review.provider,
            model=embedded.classification_review.model,
        ),
        classification_policy=embedded.classification_policy,
        parsing=embedded.parsing,
        hitl=embedded.hitl,
        artifacts=embedded.artifacts,
        runtime=embedded.runtime,
        config_contract_version=embedded.config_contract_version,
    )


def _assert_no_legacy_compliance_shape(raw_config: dict[str, Any], env_values: dict[str, Any]) -> None:
    compliance_cfg = raw_config.get("compliance")
    if isinstance(compliance_cfg, dict):
        stale_keys = [key for key in _LEGACY_COMPLIANCE_CONFIG_KEYS if key in compliance_cfg]
        if stale_keys:
            joined = ", ".join(stale_keys)
            raise ValueError(
                "Legacy compliance config keys detected in config.yaml: "
                f"{joined}. Run `hermes config migrate` to apply the v21 schema."
            )

    stale_env = [name for name in _LEGACY_COMPLIANCE_ENV_KEYS if str(env_values.get(name) or "").strip()]
    if stale_env:
        joined = ", ".join(stale_env)
        raise ValueError(
            "Legacy compliance env vars detected in project-local .env: "
            f"{joined}. Run `hermes config migrate` to apply the v21 contract."
        )


def _load_hermes_env(loaded: dict[str, Any] | None = None) -> dict[str, Any]:
    loaded = dict(loaded or load_env())
    merged = dict(loaded)
    merged.update({key: value for key, value in env_values_from_os().items() if value is not None})
    return merged


def env_values_from_os() -> dict[str, str]:
    import os

    return dict(os.environ)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coalesce_text(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _coalesce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "on"}


def _coalesce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coalesce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coalesce_tuple(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, (list, tuple, set)):
        normalized = tuple(str(item).strip() for item in value if str(item).strip())
        return normalized or default

    text = str(value).strip()
    if not text:
        return default
    return tuple(part.strip() for part in text.split(",") if part.strip()) or default
