from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from compliance_agent import __version__ as PACKAGE_VERSION
from hermes_cli.task_runtime import TaskProviderRuntime

COMPLIANCE_CONFIG_CONTRACT_VERSION = 1


@dataclass(frozen=True)
class WorkflowSettings:
    base_url: str
    timeout_seconds: int = 30
    max_retries: int = 2


@dataclass(frozen=True)
class WorkflowCredentialSet:
    contract_api_key: str = ""
    general_api_key: str = ""
    handbook_api_key: str = ""


@dataclass(frozen=True)
class ClassificationTaskConfig:
    provider: str = "deepseek"
    model: str = "deepseek-chat"


@dataclass(frozen=True)
class ClassificationPolicy:
    low_confidence_threshold: float = 0.78
    small_review_threshold: float = 0.82
    direct_big_min_parse_confidence: float = 0.45
    direct_big_parsers: tuple[str, ...] = ("pdf_ocr", "image_ocr")
    review_on_hint_conflict: bool = True
    review_on_ambiguous_types: bool = True
    max_text_chars: int = 6000
    preview_pages: int = 1
    cache_db_path: str = ".data/material_classification_cache.sqlite3"
    prompt_version: str = "material-classification-v2"
    request_timeout_seconds: float = 30.0


@dataclass(frozen=True)
class ParsingPolicy:
    min_confidence: float = 0.45
    min_chars: int = 80


@dataclass(frozen=True)
class HitlPolicy:
    confidence_threshold: float = 0.55
    high_risk_threshold: int = 1


@dataclass(frozen=True)
class ArtifactStoreConfig:
    enabled: bool = True
    dir: str = ""
    markdown: bool = True


@dataclass(frozen=True)
class ComplianceRuntimeOptions:
    enable_graph: bool = False
    stream_report_items: bool = True


@dataclass(frozen=True)
class EmbeddedComplianceConfig:
    app_version: str = PACKAGE_VERSION
    app_build: str = ""
    workflow: WorkflowSettings = field(default_factory=lambda: WorkflowSettings(base_url=""))
    classification_primary: ClassificationTaskConfig = field(default_factory=ClassificationTaskConfig)
    classification_review: ClassificationTaskConfig = field(default_factory=ClassificationTaskConfig)
    classification_policy: ClassificationPolicy = field(default_factory=ClassificationPolicy)
    parsing: ParsingPolicy = field(default_factory=ParsingPolicy)
    hitl: HitlPolicy = field(default_factory=HitlPolicy)
    artifacts: ArtifactStoreConfig = field(default_factory=ArtifactStoreConfig)
    runtime: ComplianceRuntimeOptions = field(default_factory=ComplianceRuntimeOptions)
    config_contract_version: int = COMPLIANCE_CONFIG_CONTRACT_VERSION

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedComplianceRuntimeConfig:
    app_version: str = PACKAGE_VERSION
    app_build: str = ""
    workflow: WorkflowSettings = field(default_factory=lambda: WorkflowSettings(base_url=""))
    workflow_credentials: WorkflowCredentialSet = field(default_factory=WorkflowCredentialSet)
    classification_primary: TaskProviderRuntime = field(
        default_factory=lambda: TaskProviderRuntime(
            configured_provider="deepseek",
            resolved_provider="deepseek",
            model="deepseek-chat",
            api_mode="",
            base_url="",
            api_key="",
            source="",
        )
    )
    classification_review: TaskProviderRuntime = field(
        default_factory=lambda: TaskProviderRuntime(
            configured_provider="deepseek",
            resolved_provider="deepseek",
            model="deepseek-chat",
            api_mode="",
            base_url="",
            api_key="",
            source="",
        )
    )
    classification_policy: ClassificationPolicy = field(default_factory=ClassificationPolicy)
    parsing: ParsingPolicy = field(default_factory=ParsingPolicy)
    hitl: HitlPolicy = field(default_factory=HitlPolicy)
    artifacts: ArtifactStoreConfig = field(default_factory=ArtifactStoreConfig)
    runtime: ComplianceRuntimeOptions = field(default_factory=ComplianceRuntimeOptions)
    config_contract_version: int = COMPLIANCE_CONFIG_CONTRACT_VERSION

    def snapshot(self) -> dict[str, Any]:
        return {
            "app_version": self.app_version,
            "app_build": self.app_build,
            "workflow": asdict(self.workflow),
            "workflow_credentials": asdict(self.workflow_credentials),
            "classification_primary": self.classification_primary.snapshot(),
            "classification_review": self.classification_review.snapshot(),
            "classification_policy": asdict(self.classification_policy),
            "parsing": asdict(self.parsing),
            "hitl": asdict(self.hitl),
            "artifacts": asdict(self.artifacts),
            "runtime": asdict(self.runtime),
            "config_contract_version": self.config_contract_version,
        }


def settings_fingerprint(settings: ResolvedComplianceRuntimeConfig) -> str:
    return json.dumps(settings.snapshot(), ensure_ascii=False, sort_keys=True, default=str)
