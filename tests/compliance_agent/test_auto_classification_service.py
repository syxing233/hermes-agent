from __future__ import annotations

from compliance_agent.models.schemas import MaterialType
from compliance_agent.services.auto_classification_service import (
    AutoClassification,
    MaterialClassificationService,
    _ModelAttempt,
)
from hermes_cli.task_runtime import TaskProviderRuntime


def _ready_runtime(model: str = "classifier") -> TaskProviderRuntime:
    return TaskProviderRuntime(
        configured_provider="custom",
        resolved_provider="custom",
        model=model,
        api_mode="chat_completions",
        base_url="https://example.test/v1",
        api_key="test-key",
        source="test",
        requested_provider="custom",
    )


def test_classification_does_not_read_or_write_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "material_classification_cache.sqlite3"
    service = MaterialClassificationService(
        primary_model_runtime=_ready_runtime("small"),
        review_model_runtime=_ready_runtime("review"),
        cache_db_path=str(cache_path),
    )
    calls = 0

    def fake_call_model(**kwargs):
        nonlocal calls
        calls += 1
        return _ModelAttempt(
            result=AutoClassification(
                material_type=MaterialType.MARKETING,
                confidence=0.99,
                source="model",
                reason="用于产品推广和客户触达",
            )
        )

    monkeypatch.setattr(service, "_call_model", fake_call_model)

    for _ in range(2):
        result = service.classify(
            user="tester",
            source_name="sample.txt",
            input_text="产品亮点、保障优势、适用人群、购买理由",
        )
        assert result.material_type == MaterialType.MARKETING

    assert calls == 2
    assert not cache_path.exists()
