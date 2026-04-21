from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from compliance_agent.graph.nodes import (
    adjudication_node,
    document_understanding_node,
    hitl_decision_node,
    human_review_node,
    intake_node,
    make_skill_execution_node,
    parse_quality_gate_node,
    planning_node,
    report_node,
    route_hitl,
    rules_evidence_node,
    structuring_node,
    suggestion_node,
)
from compliance_agent.models.state import WorkflowState
from compliance_agent.skills.material_skill import MaterialSkill


def build_workflow_graph(
    skills: dict[str, MaterialSkill],
):
    graph = StateGraph(WorkflowState)

    graph.add_node("intake", intake_node)
    graph.add_node("document_understanding", document_understanding_node)
    graph.add_node("structuring", structuring_node)
    graph.add_node("quality_gate", parse_quality_gate_node)
    graph.add_node("planning", planning_node)
    graph.add_node("rules_evidence", rules_evidence_node)
    graph.add_node("skills", make_skill_execution_node(skills))
    graph.add_node("adjudication", adjudication_node)
    graph.add_node("hitl_decision", hitl_decision_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("suggestion", suggestion_node)
    graph.add_node("report", report_node)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "document_understanding")
    graph.add_edge("document_understanding", "structuring")
    graph.add_edge("structuring", "quality_gate")
    graph.add_edge("quality_gate", "planning")
    graph.add_edge("planning", "rules_evidence")
    graph.add_edge("rules_evidence", "skills")
    graph.add_edge("skills", "adjudication")
    graph.add_edge("adjudication", "hitl_decision")

    graph.add_conditional_edges(
        "hitl_decision",
        route_hitl,
        {
            "human_review": "human_review",
            "skip": "suggestion",
        },
    )
    graph.add_edge("human_review", "suggestion")
    graph.add_edge("suggestion", "report")
    graph.add_edge("report", END)

    return graph.compile()
