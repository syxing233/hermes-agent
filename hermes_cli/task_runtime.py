from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from hermes_cli.runtime_provider import resolve_runtime_provider


@dataclass(frozen=True)
class TaskProviderRuntime:
    configured_provider: str
    resolved_provider: str
    model: str
    api_mode: str
    base_url: str
    api_key: str
    source: str
    requested_provider: str = ""

    def auth_ready(self) -> bool:
        token = str(self.api_key or "").strip()
        return bool(token)

    def endpoint_ready(self) -> bool:
        return bool(str(self.base_url or "").strip())

    def ready(self) -> bool:
        return self.endpoint_ready() and self.auth_ready()

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


def resolve_task_runtime(*, provider: str, model: str) -> TaskProviderRuntime:
    requested_provider = str(provider or "").strip()
    if not requested_provider:
        raise ValueError("Task provider is required")

    try:
        runtime = resolve_runtime_provider(requested=requested_provider)
    except Exception as exc:
        return TaskProviderRuntime(
            configured_provider=requested_provider,
            resolved_provider=requested_provider,
            model=str(model or "").strip(),
            api_mode="",
            base_url="",
            api_key="",
            source=f"unresolved:{exc.__class__.__name__}",
            requested_provider=requested_provider,
        )

    resolved_provider = str(runtime.get("provider") or requested_provider).strip()
    resolved_model = str(model or runtime.get("model") or "").strip()

    return TaskProviderRuntime(
        configured_provider=requested_provider,
        resolved_provider=resolved_provider,
        model=resolved_model,
        api_mode=str(runtime.get("api_mode") or "").strip(),
        base_url=str(runtime.get("base_url") or "").strip(),
        api_key=str(runtime.get("api_key") or "").strip(),
        source=str(runtime.get("source") or "").strip(),
        requested_provider=str(runtime.get("requested_provider") or requested_provider).strip(),
    )
