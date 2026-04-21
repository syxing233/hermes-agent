from __future__ import annotations

import json

from compliance_agent.graph.runner import ComplianceWorkflow
from compliance_agent.models.schemas import ComplianceRequest, MaterialType


def run_demo() -> None:
    req = ComplianceRequest(
        user="demo_user",
        query="请检测这份合同中的争议解决和违约责任风险",
        material_type=MaterialType.CONTRACT,
        input_text="""
        本合同由甲乙双方签署。争议可协商解决。乙方违约需承担违约责任。
        本文档宣称稳赚不赔并承诺100%回报。
        """,
        contract_type="通用",
        statement="甲方",
        scale="强势",
    )

    workflow = ComplianceWorkflow()
    report = workflow.run(req)

    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run_demo()
