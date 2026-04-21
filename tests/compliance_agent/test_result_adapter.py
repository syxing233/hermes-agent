from datetime import datetime

from compliance_agent.hermes.result_adapter import adapt_review_result
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


def test_result_adapter_keeps_tool_return_compact():
    report = BatchSkillReviewReport(
        task_id="review_123",
        source_count=1,
        summary=BatchSkillSummary(risk_count=1, no_risk_count=0, total_items=1),
        reports=[
            SkillReviewReport(
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
                items=[
                    SkillCheckItem(
                        check_title="争议解决条款",
                        result="存在风险",
                        reason="争议解决约定不明确",
                        basis="民法典",
                        suggestion="明确争议解决方式",
                    )
                ],
                raw=SkillRawOutput(answer_markdown="raw"),
            )
        ],
        status_trace=[
            StatusEvent(
                at=datetime.utcnow(),
                stage="最终报告输出",
                detail="sources=1",
                operation="reporting",
            )
        ],
    )

    compact = adapt_review_result(report, artifact_path="/tmp/review_123.json")

    assert compact["success"] is True
    assert compact["review_id"] == "review_123"
    assert compact["artifact_path"] == "/tmp/review_123.json"
    assert compact["top_items"][0]["check_title"] == "争议解决条款"
    assert "reports" not in compact
    assert "full_report" not in compact
