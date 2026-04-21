from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from compliance_agent.models.schemas import Chunk, ComplianceRequest, ExternalCheckResult, SkillResult


@dataclass
class SkillContext:
    request: ComplianceRequest
    chunks: list[Chunk]
    rules_context: dict
    detector_results: dict[str, ExternalCheckResult]


class Skill(Protocol):
    name: str

    def run(self, ctx: SkillContext) -> SkillResult:
        ...
