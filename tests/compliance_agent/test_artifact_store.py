import json
from datetime import datetime

from compliance_agent.hermes.artifact_store import ReviewArtifactStore
from compliance_agent.hermes.runtime_config import ArtifactStoreConfig
from compliance_agent.models.schemas import (
    BatchSkillReviewReport,
    BatchSkillSummary,
    SkillMeta,
    SkillRawOutput,
    SkillReviewReport,
    SkillSummary,
    StatusEvent,
)


def _build_report() -> BatchSkillReviewReport:
    report = SkillReviewReport(
        task_id="source_task_1",
        meta=SkillMeta(
            skill_name="contract-compliance-check",
            api_route="contract-review-2.0",
            input_file="contract.docx",
            material_type="合同",
            query="请执行合同合规审查",
            source="contract.docx",
            contract_type="通用",
        ),
        summary=SkillSummary(risk_count=1, no_risk_count=0, total_items=1),
        raw=SkillRawOutput(answer_markdown="raw"),
    )
    return BatchSkillReviewReport(
        task_id="review_123",
        source_count=1,
        summary=BatchSkillSummary(risk_count=1, no_risk_count=0, total_items=1),
        reports=[report],
        status_trace=[
            StatusEvent(
                at=datetime.utcnow(),
                stage="最终报告输出",
                detail="sources=1",
                operation="reporting",
            )
        ],
    )


def test_artifact_store_persists_under_hermes_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = ReviewArtifactStore(ArtifactStoreConfig())

    artifact = store.persist_review(
        _build_report(),
        compact_result={"review_id": "review_123", "summary": {"risk_count": 1}},
    )

    assert artifact is not None
    assert artifact.json_path == str(tmp_path / "compliance" / "reviews" / "review_123.json")
    payload = json.loads((tmp_path / "compliance" / "reviews" / "review_123.json").read_text(encoding="utf-8"))
    assert payload["review_id"] == "review_123"
    assert payload["json_path"] == artifact.json_path
