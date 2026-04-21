import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from compliance_agent.models.schemas import (
    BatchSkillReviewReport,
    BatchSkillSummary,
    SkillCheckItem,
    SkillMeta,
    SkillRawOutput,
    SkillReviewReport,
    SkillSummary,
    StatusEvent,
)
from tools.compliance_tool import (
    _build_upload_file_payload,
    _normalize_material_type,
    check_compliance_agent_requirements,
    compliance_assistant,
    compliance_get_report,
    compliance_health,
    compliance_review,
)


def _build_report(material_type: str = "合同") -> BatchSkillReviewReport:
    item = SkillCheckItem(
        check_title="争议解决条款",
        result="存在风险",
        reason="争议解决约定不明确",
        source_excerpt="发生争议时协商解决",
        basis="民法典",
        suggestion="明确法院或仲裁机构",
    )
    report = SkillReviewReport(
        task_id="source_task_1",
        meta=SkillMeta(
            skill_name="contract-compliance-check",
            api_route="contract-review-2.0",
            input_file="contract.docx",
            material_type=material_type,
            query="请执行合同合规审查",
            source="contract.docx",
            contract_type="通用",
        ),
        summary=SkillSummary(risk_count=1, no_risk_count=0, total_items=1),
        items=[item],
        raw=SkillRawOutput(answer_markdown="raw markdown"),
        supported=True,
        status_trace=[
            StatusEvent(
                at=datetime.utcnow(),
                stage="Skill执行层",
                detail="skill=contract-compliance-check",
                operation="checking",
            )
        ],
    )
    return BatchSkillReviewReport(
        task_id="review_123",
        source_count=1,
        summary=BatchSkillSummary(
            risk_count=1,
            no_risk_count=0,
            total_items=1,
            supported_count=1,
            unsupported_count=0,
        ),
        reports=[report],
        status_trace=[
            StatusEvent(
                at=datetime.utcnow(),
                stage="最终报告输出",
                detail="sources=1,total_items=1",
                operation="reporting",
            )
        ],
    )


class _FakeIngestService:
    def __init__(self, report: BatchSkillReviewReport):
        self.report = report
        self.calls = []

    def review_sources(
        self,
        sources,
        material_type=None,
        hint_material_type=None,
        user="anonymous",
        context_text=None,
        status_callback=None,
        item_callback=None,
    ):
        self.calls.append(
            {
                "sources": sources,
                "material_type": material_type,
                "hint_material_type": hint_material_type,
                "user": user,
                "context_text": context_text,
            }
        )
        if status_callback:
            status_callback(
                StatusEvent(
                    at=datetime.utcnow(),
                    stage="物料自动分类",
                    detail="material_type=合同",
                    operation="analyzing",
                )
            )
        if item_callback:
            item_callback(self.report.reports[0].meta, self.report.reports[0].items[0])
        return self.report


class _FakeArtifactStore:
    def __init__(self, root: Path):
        self.root = root
        self.persisted = []

    def persist_review(self, report, compact_result=None):
        path = self.root / f"{report.task_id}.json"
        path.write_text("{}", encoding="utf-8")
        self.persisted.append({"report": report, "compact_result": compact_result, "path": path})
        return SimpleNamespace(review_id=report.task_id, json_path=str(path), markdown_path=None)

    def read_review(self, review_id):
        return self.root / f"{review_id}.json", {
            "review_id": review_id,
            "json_path": str(self.root / f"{review_id}.json"),
            "summary": {"risk_count": 1},
            "status_trace_summary": [{"stage": "最终报告输出"}],
            "compact_result": {"review_id": review_id},
            "report": {"task_id": review_id, "reports": []},
        }

    def root_dir(self):
        return self.root


def test_check_requirements_is_embedded_runtime():
    assert check_compliance_agent_requirements() is True


def test_normalize_material_type_supports_aliases():
    assert _normalize_material_type("contract") == "合同"
    assert _normalize_material_type("说明书") == "产品说明书"
    assert _normalize_material_type("海报") == "海报"
    assert _normalize_material_type("") is None


def test_build_upload_file_payload_uses_document_and_image_types(tmp_path):
    doc = tmp_path / "sample.docx"
    doc.write_text("x", encoding="utf-8")
    image = tmp_path / "sample.png"
    image.write_bytes(b"png")

    assert _build_upload_file_payload(doc)["type"] == "document"
    assert _build_upload_file_payload(image)["type"] == "image"


def test_compliance_health_reports_embedded_runtime(monkeypatch, tmp_path):
    runtime = SimpleNamespace(
        settings=SimpleNamespace(app_version="1.2.3", app_build="build-1"),
        health_payload=lambda: {"embedded": True, "artifact_store_dir": str(tmp_path)},
    )
    monkeypatch.setattr("tools.compliance_tool.get_runtime", lambda: runtime)

    result = json.loads(compliance_health())

    assert result["success"] is True
    assert result["service"] == "embedded-compliance-engine"
    assert result["health"]["embedded"] is True


def test_compliance_review_requires_input():
    result = json.loads(compliance_review())
    assert "Provide at least one file path or non-empty text" in result["error"]


def test_compliance_review_uses_embedded_runtime_and_returns_compact_result(monkeypatch, tmp_path):
    sample = tmp_path / "contract.docx"
    sample.write_text("contract body", encoding="utf-8")
    report = _build_report()
    ingest_service = _FakeIngestService(report)
    artifact_store = _FakeArtifactStore(tmp_path)
    runtime = SimpleNamespace(
        ingest_service=ingest_service,
        artifact_store=artifact_store,
        workflow_client=SimpleNamespace(_client=SimpleNamespace(timeout=30)),
        classifier=SimpleNamespace(request_timeout_seconds=30),
    )
    monkeypatch.setattr("tools.compliance_tool.get_runtime", lambda: runtime)

    result = json.loads(
        compliance_review(
            file_paths=[str(sample)],
            text="补充说明",
            material_type="contract",
            timeout_seconds=33,
        )
    )

    call = ingest_service.calls[0]
    assert call["material_type"].value == "合同"
    assert call["context_text"] == "补充说明"
    assert call["sources"][0].local_path == str(sample.resolve())
    assert runtime.workflow_client._client.timeout == 33
    assert runtime.classifier.request_timeout_seconds == 33
    assert result["success"] is True
    assert result["review_id"] == "review_123"
    assert result["artifact_path"].endswith("review_123.json")
    assert "reports" not in result
    assert result["top_items"][0]["check_title"] == "争议解决条款"


def test_compliance_assistant_review_path_does_not_use_standalone_memory(monkeypatch):
    monkeypatch.setattr(
        "tools.compliance_tool.compliance_review",
        lambda **kwargs: json.dumps(
            {
                "success": True,
                "review_id": "review_123",
                "material_type": "海报",
                "summary": {"risk_count": 1},
                "top_items": [{"check_title": "夸大宣传"}],
                "artifact_path": "/tmp/review_123.json",
            },
            ensure_ascii=False,
        ),
    )

    result = json.loads(
        compliance_assistant(
            message="帮我检查这张海报",
            material_type="poster",
            input_file_path="/tmp/poster.png",
        )
    )

    assert result["mode"] == "detection"
    assert result["uses_standalone_memory"] is False
    assert result["deprecated"] is True
    assert result["review_id"] == "review_123"


def test_compliance_assistant_message_only_returns_compatibility_notice():
    result = json.loads(compliance_assistant(message="继续上次的会话"))

    assert result["success"] is True
    assert result["mode"] == "compatibility"
    assert result["uses_standalone_memory"] is False


def test_compliance_get_report_reads_artifact(monkeypatch, tmp_path):
    runtime = SimpleNamespace(artifact_store=_FakeArtifactStore(tmp_path))
    monkeypatch.setattr("tools.compliance_tool.get_runtime", lambda: runtime)

    result = json.loads(compliance_get_report("review_123", include_full_report=True))

    assert result["success"] is True
    assert result["review_id"] == "review_123"
    assert result["artifact_path"].endswith("review_123.json")
    assert result["full_report"]["task_id"] == "review_123"
