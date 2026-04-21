from __future__ import annotations

import operator
from typing import Annotated, Any, Callable, TypedDict

from compliance_agent.models.schemas import (
    AdjudicationResult,
    Chunk,
    ComplianceRequest,
    DetectReport,
    DocumentBlock,
    DocumentQuality,
    ExecutionPlan,
    HumanReview,
    SkillResult,
    StatusEvent,
    Suggestion,
)
from compliance_agent.hermes.runtime_config import HitlPolicy, ParsingPolicy


class WorkflowState(TypedDict, total=False):
    request: ComplianceRequest
    task_id: str

    # layers
    raw_text: str
    blocks: list[DocumentBlock]
    chunks: list[Chunk]
    parse_quality: DocumentQuality
    quality_needs_review: bool
    parsing_policy: ParsingPolicy
    plan: ExecutionPlan
    rules_context: dict[str, Any]
    status_callback: Callable[[StatusEvent], None]

    # collection with reducers
    skill_results: Annotated[list[SkillResult], operator.add]
    status_trace: Annotated[list[StatusEvent], operator.add]
    errors: Annotated[list[str], operator.add]

    # decision outputs
    adjudication: AdjudicationResult
    human_review: HumanReview
    needs_human_review: bool
    hitl_policy: HitlPolicy
    suggestions: list[Suggestion]
    final_report: DetectReport
