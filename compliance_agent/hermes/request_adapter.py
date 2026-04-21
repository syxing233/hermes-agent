from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from compliance_agent.models.schemas import MaterialType, normalize_material_type
from compliance_agent.services.ingest_service import IngestSource

_MATERIAL_TYPE_ALIASES = {
    "contract": "合同",
    "合同": "合同",
    "clausebook": "条款书",
    "条款书": "条款书",
    "handbook": "产品说明书",
    "product handbook": "产品说明书",
    "product_handbook": "产品说明书",
    "说明书": "产品说明书",
    "产品说明书": "产品说明书",
    "marketing": "营销物料",
    "marketing material": "营销物料",
    "marketing_material": "营销物料",
    "营销物料": "营销物料",
    "poster": "海报",
    "海报": "海报",
    "other": "其它",
    "其它": "其它",
}


@dataclass(frozen=True)
class AdaptedReviewRequest:
    sources: list[IngestSource]
    material_type: MaterialType | None
    hint_material_type: MaterialType | None
    user: str
    context_text: str | None = None
    text_as_source: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def normalize_material_type_hint(value: Any) -> MaterialType | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    mapped = _MATERIAL_TYPE_ALIASES.get(text.lower(), text)
    return normalize_material_type(mapped)


def _normalize_unicode_path(path_str: str) -> str:
    """Apply NFC normalization so LLM-supplied text (NFC) matches macOS
    HFS+ filenames (NFD-decomposed). Safe on all platforms: NFC→NFC is a
    no-op on Linux/Windows."""
    return unicodedata.normalize("NFC", path_str)


def coerce_file_paths(
    file_paths: Any,
    cwd: Path | str | None = None,
) -> list[Path]:
    """Resolve and validate file paths for compliance review.

    * Expands ``~`` (expanduser) and ``$VAR`` / ``${VAR}`` (expandvars).
    * Resolves relative paths against *cwd* (defaults to ``Path.cwd()``).
    * Applies NFC Unicode normalization for macOS compatibility.
    * Checks that the resolved path exists, is a regular file, and is readable.
    """
    if not file_paths:
        return []

    raw_paths = [file_paths] if isinstance(file_paths, (str, Path)) else list(file_paths)
    base_dir = Path(str(cwd)) if cwd is not None else Path.cwd()
    resolved: list[Path] = []
    for raw in raw_paths:
        raw_str = _normalize_unicode_path(str(raw).strip())
        if len(raw_str) >= 2 and (
            (raw_str.startswith('"') and raw_str.endswith('"'))
            or (raw_str.startswith("'") and raw_str.endswith("'"))
        ):
            raw_str = raw_str[1:-1].strip()
        if not raw_str:
            continue

        expanded = os.path.expandvars(os.path.expanduser(raw_str))
        path = Path(expanded)
        if not path.is_absolute():
            path = base_dir / path

        try:
            resolved_path = path.resolve()
        except Exception:
            resolved_path = path

        if not resolved_path.exists():
            nfd_path_str = unicodedata.normalize("NFD", str(resolved_path))
            nfd_candidate = Path(nfd_path_str)
            if nfd_candidate.exists() and nfd_candidate.is_file():
                resolved_path = nfd_candidate.resolve()
            else:
                raise FileNotFoundError(
                    f"File not found: {resolved_path}. "
                    f"Check that the path is correct and the file exists."
                )

        if not resolved_path.is_file():
            raise ValueError(
                f"Path is not a regular file: {resolved_path}. "
                f"Directories are not accepted."
            )

        if not os.access(resolved_path, os.R_OK):
            raise PermissionError(
                f"File is not readable (permission denied): {resolved_path}. "
                f"Check file permissions with 'ls -la'."
            )

        resolved.append(resolved_path)
    return resolved


def adapt_review_request(
    *,
    file_paths: Any = None,
    text: str | None = None,
    material_type: str | None = None,
    user: str = "anonymous",
    conversation_id: str | None = None,
    text_as_source: bool = False,
    task_id: str | None = None,
    cwd: Path | str | None = None,
) -> AdaptedReviewRequest:
    normalized_text = (text or "").strip()
    resolved_paths = coerce_file_paths(file_paths, cwd=cwd)
    normalized_material_type = normalize_material_type_hint(material_type)

    if not resolved_paths and not normalized_text:
        raise ValueError("Provide at least one file path or non-empty text for compliance review.")

    sources = [
        IngestSource(
            source_name=path.name,
            source_type="file",
            local_path=str(path),
        )
        for path in resolved_paths
    ]

    use_text_as_source = bool(normalized_text) and (text_as_source or not sources)
    if use_text_as_source:
        sources.append(
            IngestSource(
                source_name=f"inline_text_{len(sources) + 1}",
                source_type="text",
                input_text=normalized_text,
            )
        )

    context_text = None if use_text_as_source else (normalized_text or None)
    metadata = {
        "conversation_id": (conversation_id or "").strip(),
        "task_id": (task_id or "").strip(),
    }

    return AdaptedReviewRequest(
        sources=sources,
        material_type=normalized_material_type,
        hint_material_type=normalized_material_type,
        user=(user or "anonymous").strip() or "anonymous",
        context_text=context_text,
        text_as_source=use_text_as_source,
        metadata=metadata,
    )