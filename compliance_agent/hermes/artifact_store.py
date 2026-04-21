from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from compliance_agent.hermes.runtime_config import ArtifactStoreConfig
from compliance_agent.hermes.session_policy import compact_summary, summarize_status_trace
from compliance_agent.models.schemas import BatchSkillReviewReport
from hermes_constants import get_hermes_home


@dataclass(frozen=True)
class StoredArtifact:
    review_id: str
    json_path: str
    markdown_path: str | None = None


class ReviewArtifactStore:
    def __init__(self, settings: ArtifactStoreConfig):
        self.settings = settings

    def is_enabled(self) -> bool:
        return bool(self.settings.enabled)

    def root_dir(self) -> Path:
        configured = (self.settings.dir or "").strip()
        if configured:
            path = Path(configured).expanduser()
            if not path.is_absolute():
                path = (get_hermes_home() / path).resolve()
            return path
        return get_hermes_home() / "compliance" / "reviews"

    def persist_review(
        self,
        report: BatchSkillReviewReport,
        *,
        compact_result: dict[str, Any] | None = None,
    ) -> StoredArtifact | None:
        if not self.is_enabled():
            return None

        root = self.root_dir()
        root.mkdir(parents=True, exist_ok=True)
        review_id = report.task_id
        json_path = root / f"{review_id}.json"
        markdown_path = root / f"{review_id}.md" if self.settings.markdown else None

        payload = {
            "review_id": review_id,
            "stored_at": datetime.now(timezone.utc).isoformat(),
            "json_path": str(json_path),
            "markdown_path": str(markdown_path) if markdown_path is not None else None,
            "summary": compact_summary(report.summary),
            "status_trace_summary": summarize_status_trace(report.status_trace),
            "report": report.model_dump(mode="json"),
            "compact_result": compact_result or {},
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        if markdown_path is not None:
            markdown_path.write_text(
                _build_markdown_summary(
                    review_id=review_id,
                    compact_result=compact_result or {},
                    json_path=str(json_path),
                ),
                encoding="utf-8",
            )

        return StoredArtifact(
            review_id=review_id,
            json_path=str(json_path),
            markdown_path=str(markdown_path) if markdown_path is not None else None,
        )

    def read_review(self, review_id: str) -> tuple[Path, dict[str, Any]]:
        path = self._resolve_review_path(review_id)
        if not path.exists():
            raise FileNotFoundError(f"Compliance review artifact not found: {path}")

        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Compliance review artifact is not a JSON object: {path}")
        return path, payload

    def _resolve_review_path(self, review_id: str) -> Path:
        raw = (review_id or "").strip()
        if not raw:
            raise ValueError("review_id is required")

        candidate = Path(raw).expanduser()
        if candidate.suffix.lower() == ".json":
            if not candidate.is_absolute():
                candidate = (self.root_dir() / candidate).resolve()
            return candidate
        return self.root_dir() / f"{raw}.json"


def _build_markdown_summary(review_id: str, compact_result: dict[str, Any], json_path: str) -> str:
    summary = compact_result.get("summary") or {}
    material_type = compact_result.get("material_type") or "未识别"
    top_items = compact_result.get("top_items") or []

    lines = [
        f"# Compliance Review {review_id}",
        "",
        f"- material_type: {material_type}",
        f"- source_count: {compact_result.get('source_count', 0)}",
        f"- total_items: {summary.get('total_items', 0)}",
        f"- risk_count: {summary.get('risk_count', 0)}",
        f"- artifact_path: {json_path}",
        "",
        "## Top Items",
        "",
    ]

    if top_items:
        for index, item in enumerate(top_items, start=1):
            lines.append(
                f"{index}. {item.get('check_title', '检测项')} | "
                f"{item.get('result', '')} | {item.get('reason', '')}"
            )
    else:
        lines.append("1. No extracted items.")

    return "\n".join(lines).strip() + "\n"
