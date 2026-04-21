from __future__ import annotations

import yaml

from compliance_agent.hermes.config_adapter import (
    load_compliance_settings,
    load_embedded_compliance_config,
)
from compliance_agent.hermes.runtime_config import WorkflowCredentialSet
from compliance_agent.models.schemas import MaterialType
from compliance_agent.skills.registry import get_material_skill_spec
from hermes_cli.task_runtime import TaskProviderRuntime


def test_load_embedded_compliance_config_reads_nested_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "compliance": {
                    "workflow": {"base_url": "http://example.test/v1", "timeout_seconds": 55},
                    "classification": {
                        "primary": {"provider": "deepseek", "model": "deepseek-chat"},
                        "review": {"provider": "deepseek", "model": "deepseek-reasoner"},
                    },
                    "artifacts": {"enabled": False},
                }
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    embedded = load_embedded_compliance_config()

    assert embedded.workflow.base_url == "http://example.test/v1"
    assert embedded.workflow.timeout_seconds == 55
    assert embedded.classification_primary.provider == "deepseek"
    assert embedded.classification_review.model == "deepseek-reasoner"
    assert embedded.artifacts.enabled is False


def test_load_compliance_settings_reads_project_local_secrets_and_resolves_runtimes(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "compliance": {
                    "workflow": {"base_url": "http://example.test/v1"},
                    "classification": {
                        "primary": {"provider": "deepseek", "model": "deepseek-chat"},
                        "review": {"provider": "custom-classifier", "model": "acme-review"},
                    },
                }
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "COMPLIANCE_CONTRACT_API_KEY=contract-key\n"
        "COMPLIANCE_GENERAL_API_KEY=general-key\n"
        "COMPLIANCE_HANDBOOK_API_KEY=handbook-key\n",
        encoding="utf-8",
    )

    runtimes = {
        "deepseek": TaskProviderRuntime(
            configured_provider="deepseek",
            resolved_provider="deepseek",
            model="deepseek-chat",
            api_mode="chat_completions",
            base_url="https://api.deepseek.com",
            api_key="deepseek-key",
            source="env",
            requested_provider="deepseek",
        ),
        "custom-classifier": TaskProviderRuntime(
            configured_provider="custom-classifier",
            resolved_provider="custom",
            model="acme-review",
            api_mode="chat_completions",
            base_url="https://custom.example/v1",
            api_key="custom-key",
            source="custom_provider",
            requested_provider="custom-classifier",
        ),
    }
    monkeypatch.setattr(
        "compliance_agent.hermes.config_adapter.resolve_task_runtime",
        lambda *, provider, model: runtimes[provider],
    )

    settings = load_compliance_settings()

    assert settings.workflow.base_url == "http://example.test/v1"
    assert settings.workflow_credentials.contract_api_key == "contract-key"
    assert settings.workflow_credentials.general_api_key == "general-key"
    assert settings.workflow_credentials.handbook_api_key == "handbook-key"
    assert settings.classification_primary.configured_provider == "deepseek"
    assert settings.classification_review.configured_provider == "custom-classifier"


def test_load_embedded_compliance_config_rejects_legacy_flat_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "compliance": {
                    "workflow_base_url": "http://legacy.example/v1",
                }
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    try:
        load_embedded_compliance_config()
    except ValueError as exc:
        assert "Legacy compliance config keys detected" in str(exc)
    else:
        raise AssertionError("expected legacy compliance config validation error")


def test_load_embedded_compliance_config_rejects_legacy_env_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "compliance": {
                    "workflow": {"base_url": "http://example.test/v1"},
                }
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("CONTRACT_API_KEY=legacy-contract\n", encoding="utf-8")

    try:
        load_embedded_compliance_config()
    except ValueError as exc:
        assert "Legacy compliance env vars detected" in str(exc)
    else:
        raise AssertionError("expected legacy compliance env validation error")


def test_handbook_skill_resolves_api_key_from_workflow_credentials():
    spec = get_material_skill_spec(MaterialType.HANDBOOK)

    assert spec is not None
    assert spec.resolve_api_key(WorkflowCredentialSet(handbook_api_key="project-local-key")) == "project-local-key"
    assert spec.resolve_api_key(WorkflowCredentialSet()) == ""
