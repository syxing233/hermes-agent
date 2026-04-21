from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable

from compliance_agent.graph.runner import ComplianceWorkflow
from compliance_agent.hermes.artifact_store import ReviewArtifactStore
from compliance_agent.hermes.config_adapter import load_compliance_settings
from compliance_agent.hermes.runtime_config import ResolvedComplianceRuntimeConfig, settings_fingerprint
from compliance_agent.services.auto_classification_service import MaterialClassificationService
from compliance_agent.services.external_workflow_client import ExternalWorkflowClient
from compliance_agent.services.ingest_service import IngestReviewService
from compliance_agent.services.material_skill_service import MaterialSkillRouter


@dataclass
class HermesComplianceRuntime:
    settings: ResolvedComplianceRuntimeConfig
    workflow_client: ExternalWorkflowClient
    classifier: MaterialClassificationService
    workflow: ComplianceWorkflow
    ingest_service: IngestReviewService
    artifact_store: ReviewArtifactStore
    graph_enabled: bool = False
    graph_builder: Callable[..., Any] | None = None

    def close(self) -> None:
        try:
            self.workflow_client.close()
        except Exception:
            pass

    def health_payload(self) -> dict[str, Any]:
        workflow_keys = self.settings.workflow_credentials
        primary = self.settings.classification_primary
        review = self.settings.classification_review
        return {
            "embedded": True,
            "config_contract_version": self.settings.config_contract_version,
            "graph_enabled": self.graph_enabled,
            "artifact_store_dir": str(self.artifact_store.root_dir()),
            "workflow": {
                "base_url": self.settings.workflow.base_url,
                "timeout_seconds": self.settings.workflow.timeout_seconds,
                "max_retries": self.settings.workflow.max_retries,
                "ready": bool(self.settings.workflow.base_url),
                "credentials": {
                    "contract_api_key": bool(workflow_keys.contract_api_key),
                    "general_api_key": bool(workflow_keys.general_api_key),
                    "handbook_api_key": bool(workflow_keys.handbook_api_key),
                },
            },
            "classification_primary": _runtime_health(primary),
            "classification_review": _runtime_health(review),
            "artifacts": {
                "enabled": self.settings.artifacts.enabled,
                "markdown": self.settings.artifacts.markdown,
            },
        }


def _runtime_health(runtime: Any) -> dict[str, Any]:
    return {
        "provider": runtime.configured_provider,
        "resolved_provider": runtime.resolved_provider,
        "model": runtime.model,
        "api_mode": runtime.api_mode,
        "base_url": runtime.base_url,
        "source": runtime.source,
        "auth_ready": runtime.auth_ready(),
        "ready": runtime.ready(),
    }


_runtime_lock = RLock()
_runtime_cache_key: str | None = None
_runtime_cache: HermesComplianceRuntime | None = None


def get_runtime(*, force_reload: bool = False) -> HermesComplianceRuntime:
    global _runtime_cache_key, _runtime_cache

    settings = load_compliance_settings()
    cache_key = settings_fingerprint(settings)

    with _runtime_lock:
        if not force_reload and _runtime_cache is not None and _runtime_cache_key == cache_key:
            return _runtime_cache

        if _runtime_cache is not None:
            _runtime_cache.close()

        workflow_client = ExternalWorkflowClient(
            base_url=settings.workflow.base_url,
            timeout_seconds=settings.workflow.timeout_seconds,
            max_retries=settings.workflow.max_retries,
        )
        classifier = MaterialClassificationService(
            client=workflow_client,
            workflow_credentials=settings.workflow_credentials,
            primary_model_runtime=settings.classification_primary,
            review_model_runtime=settings.classification_review,
            classification_policy=settings.classification_policy,
        )
        router = MaterialSkillRouter(
            client=workflow_client,
            workflow_credentials=settings.workflow_credentials,
            workflow_settings=settings.workflow,
        )
        workflow = ComplianceWorkflow(
            router=router,
            stream_report_items_enabled=settings.runtime.stream_report_items,
        )
        ingest_service = IngestReviewService(workflow=workflow, classifier=classifier)
        artifact_store = ReviewArtifactStore(settings.artifacts)

        graph_builder = None
        graph_enabled = False
        if settings.runtime.enable_graph:
            try:
                from compliance_agent.graph.builder import build_workflow_graph

                graph_builder = build_workflow_graph
                graph_enabled = True
            except ModuleNotFoundError:
                graph_enabled = False

        _runtime_cache = HermesComplianceRuntime(
            settings=settings,
            workflow_client=workflow_client,
            classifier=classifier,
            workflow=workflow,
            ingest_service=ingest_service,
            artifact_store=artifact_store,
            graph_enabled=graph_enabled,
            graph_builder=graph_builder,
        )
        _runtime_cache_key = cache_key
        return _runtime_cache
