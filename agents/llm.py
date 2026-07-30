"""Agent connection resolution: DB (UI-connected) → env fallback.

Local-first: one global connection per machine (no installations).
"""

from dataclasses import dataclass

from sqlalchemy import select

from agents.backends import AgentBackend, ClaudeCodeBackend, CodexBackend
from core.config import get_settings
from core.crypto import EncryptionError, decrypt_key
from core.db.models import AgentConnection as AgentConnectionRow
from core.db.session import get_session_factory
from core.logging import get_logger

log = get_logger("llm")

_PRICING = {
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-opus-4-5": (5.00, 25.00),
}

PROVIDERS = ("anthropic", "claude_code", "codex")


class BudgetExceeded(Exception):
    pass


@dataclass
class AgentConnection:
    provider: str  # 'anthropic' | 'claude_code' | 'codex'
    credential: str

    @property
    def is_metered(self) -> bool:
        return self.provider == "anthropic"


async def resolve_agent() -> AgentConnection:
    """The machine's connected coding agent, or the env fallback."""
    async with get_session_factory()() as session:
        row = await session.scalar(
            select(AgentConnectionRow).order_by(AgentConnectionRow.created_at.desc()).limit(1)
        )
        if row:
            try:
                return AgentConnection(row.provider, decrypt_key(row.ciphertext))
            except EncryptionError:
                await log.aerror("stored agent credential undecryptable")
    fallback = get_settings().anthropic_api_key
    if fallback:
        return AgentConnection("anthropic", fallback)
    raise RuntimeError(
        "No coding agent connected: connect Claude Code or Codex in the dashboard "
        "(or set ANTHROPIC_API_KEY)"
    )


def make_cli_backend(conn: AgentConnection, model: str | None = None) -> AgentBackend:
    if conn.provider == "claude_code":
        return ClaudeCodeBackend(conn.credential, model)
    if conn.provider == "codex":
        return CodexBackend(conn.credential, model)
    raise ValueError(f"not a CLI provider: {conn.provider}")


def make_chat_model(model: str, api_key: str, temperature: float = 0.2):
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=model, api_key=api_key, temperature=temperature, max_tokens=8192)


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = _PRICING.get(model, (3.00, 15.00))
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


def check_budget(state_cost: float, metered: bool = True) -> None:
    """Raise BudgetExceeded if the per-scan cap is hit.

    Only enforced for metered (API-key) usage — CLI backends bill the user's
    subscription, where the dollar figure is an API-equivalent estimate, not
    real billing. (Their real constraint is rate limits, not dollars.)
    """
    if metered and state_cost >= get_settings().scan_budget_usd:
        raise BudgetExceeded(
            f"scan budget ${get_settings().scan_budget_usd:.2f} exceeded (${state_cost:.4f} spent)"
        )
