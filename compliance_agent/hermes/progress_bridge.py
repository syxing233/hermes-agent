from __future__ import annotations

from dataclasses import dataclass

from compliance_agent.hermes.session_policy import summarize_status_trace
from compliance_agent.models.schemas import SkillCheckItem, SkillMeta, StatusEvent


@dataclass(frozen=True)
class ProgressItem:
    source: str
    material_type: str
    check_title: str
    result: str
    reason: str
    basis: str
    suggestion: str


class HermesProgressBridge:
    def __init__(self):
        self.status_events: list[StatusEvent] = []
        self.item_events: list[ProgressItem] = []

    def status_callback(self, event: StatusEvent) -> None:
        self.status_events.append(event)

    def item_callback(self, meta: SkillMeta, item: SkillCheckItem) -> None:
        self.item_events.append(
            ProgressItem(
                source=(meta.source or meta.input_file or meta.skill_name or "输入内容").strip(),
                material_type=(meta.material_type or "").strip(),
                check_title=(item.check_title or "检测项").strip(),
                result=(item.result or "").strip(),
                reason=(item.reason or "").strip(),
                basis=(item.basis or "").strip(),
                suggestion=(item.suggestion or "").strip(),
            )
        )

    def top_items(self) -> list[dict[str, str]]:
        return [
            {
                "source": entry.source,
                "material_type": entry.material_type,
                "check_title": entry.check_title,
                "result": entry.result,
                "reason": entry.reason,
                "basis": entry.basis,
                "suggestion": entry.suggestion,
            }
            for entry in self.item_events
        ]

    def status_trace_summary(self) -> list[dict[str, object]]:
        return summarize_status_trace(self.status_events)
