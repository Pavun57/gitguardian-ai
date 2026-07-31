"""Langfuse tracing (SDK v4/OTel API) — observability for every pipeline run.

Chosen over LangSmith because it's open-source and self-hostable: traces
(which contain code snippets) stay on your machine. Compose profile
`langfuse` runs the full stack at http://localhost:3100 with project id
`gitguardian` (auto-provisioned).

Every `gitguardian commit` creates one trace; LLM calls are recorded as
generations (model, tokens, cost). The trace URL is stored on the scan row
so the dashboard can deep-link into the Langfuse UI.

API notes (langfuse-python v4):
- `start_as_current_span/generation` are gone → unified `start_observation`.
- We deliberately do NOT use `start_as_current_observation`: LangGraph runs
  nodes in different contextvars contexts, so a context manager entered at
  the CLI and exited later crashes with "Token was created in a different
  Context". Explicit start/end + trace_context linking is context-free.
"""

import contextvars
from typing import Any

from core.appconfig import get_config
from core.logging import get_logger

log = get_logger("tracing")

_client = None
_keys_checked = False
_host = "http://localhost:3100"

_current: contextvars.ContextVar["ScanTracer | None"] = contextvars.ContextVar(
    "gg_tracer", default=None
)


async def _get_client():
    """Langfuse client from UI-saved keys (app_config) or env. None if unconfigured."""
    global _client, _keys_checked, _host
    if _client:
        return _client
    if _keys_checked:
        return None
    _keys_checked = True

    public_key = await get_config("langfuse_public_key")
    secret_key = await get_config("langfuse_secret_key")
    host = await get_config("langfuse_host") or "http://localhost:3100"
    if not (public_key and secret_key):
        return None
    try:
        from langfuse import Langfuse

        _client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        _host = host.rstrip("/")
        return _client
    except Exception as e:
        await log.awarning("langfuse init failed", error=str(e)[:200])
        return None


def current_tracer() -> "ScanTracer | None":
    return _current.get()


class ScanTracer:
    """One pipeline run = one trace. No-op-safe when Langfuse isn't configured."""

    def __init__(self, client):
        self._client = client
        self._root = None
        self.trace_id: str | None = None

    @classmethod
    async def create(cls, name: str, metadata: dict[str, Any]) -> "ScanTracer":
        client = await _get_client()
        tracer = cls(client)
        if client is not None:
            root = client.start_observation(name=name, as_type="span", metadata=metadata)
            tracer._root = root
            tracer.trace_id = root.trace_id
        _current.set(tracer)
        return tracer

    @property
    def url(self) -> str | None:
        if not self.trace_id:
            return None
        return f"{_host}/project/gitguardian/traces/{self.trace_id}"

    def _ctx(self) -> dict | None:
        return {"trace_id": self.trace_id} if self.trace_id else None

    def generation(
        self,
        name: str,
        model: str,
        input: Any,
        output: Any,
        usage: dict | None = None,
        cost: float | None = None,
    ) -> None:
        if not self._client:
            return
        gen = self._client.start_observation(
            name=name,
            as_type="generation",
            trace_context=self._ctx(),
            model=model,
            input=input,
            usage_details=usage,
            cost_details={"total": cost} if cost is not None else None,
        )
        gen.update(output=output)
        gen.end()

    def event(self, name: str, **metadata) -> None:
        if not self._client:
            return
        span = self._client.start_observation(
            name=name, as_type="span", trace_context=self._ctx(), metadata=metadata or None
        )
        span.end()

    def close(self) -> None:
        if self._root:
            self._root.end()
        if self._client:
            self._client.flush()
