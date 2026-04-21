__all__: list[str] = []

try:
    from compliance_agent.graph.builder import build_workflow_graph
    from compliance_agent.graph.runner import ComplianceWorkflow

    __all__ = ["build_workflow_graph", "ComplianceWorkflow"]
except ModuleNotFoundError as exc:
    # Allow importing submodules (e.g., graph.nodes in tests) even when
    # optional runtime dependency `langgraph` is not installed.
    if exc.name != "langgraph":
        raise
