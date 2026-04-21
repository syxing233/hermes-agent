from __future__ import annotations

from itertools import islice
from uuid import uuid4

from compliance_agent.models.schemas import Evidence


def new_finding_id() -> str:
    return f"fdg_{uuid4().hex[:12]}"


def first_evidence(chunks: list, fallback: str = "无") -> list[Evidence]:
    if not chunks:
        return [Evidence(quote=fallback, page=1)]
    chunk = next(iter(chunks))
    quote = chunk.text[:120] if chunk.text else fallback
    return [Evidence(quote=quote, page=chunk.page, chunk_id=chunk.chunk_id)]


def sample_chunks(chunks: list, limit: int = 3):
    return list(islice(chunks, limit))
