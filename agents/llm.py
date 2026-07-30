"""LLM/agent access: credential resolution, backends, cost tracking.

Resolution order per installation:
  1. The installation's stored agent connection (api_keys table): provider is
     'anthropic' (API key), 'claude_code' (OAuth token for the Claude Code CLI),
     or 'codex' (OpenAI key or ChatGPT auth.json).
  2. Env fallback: ANTHROPIC_API_KEY (single-tenant/dev).

Budget caps apply to metered (API-key) usage. CLI backends bill the user's own
subscription — we still record tokens, but budget enforcement can't apply to
what we can't price, so scans on CLI backends log usage instead of capping.
"""

from dataclasses import dataclass

from sqlalchemy import select

from agents.backends import AgentBackend, ClaudeCodeBackend, CodexBackend
from core.config import get_settings
from core.crypto import EncryptionError, decrypt_key
from core.db.models import ApiKey
from core.db.session import get_session_factory
from core.logging import get_logger

log = get_logger("llm")

# USD per 1M tokens (input, output) — keep in sync with Anthropic pricing.
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


async def resolve_agent(installation_id: int | None) -> AgentConnection:
    """Which agent should work on this installation's fixes?

    Order: installation-specific connection → global default (NULL) → env.
    """
    if installation_id is not None:
        async with get_session_factory()() as session:
            row = await session.scalar(
                select(ApiKey)
                .where(
                    ApiKey.installation_id == installation_id,
                    ApiKey.provider.in_(PROVIDERS),
                )
                .order_by(ApiKey.created_at.desc())
                .limit(1)
            )
            if row:
                try:
                    return AgentConnection(row.provider, decrypt_key(row.ciphertext))
                except EncryptionError:
                    await log.aerror(
                        "stored credential undecryptable", installation_id=installation_id
                    )

    # Global default connection (installation_id IS NULL)
    async with get_session_factory()() as session:
        row = await session.scalar(
            select(ApiKey)
            .where(ApiKey.installation_id.is_(None), ApiKey.provider.in_(PROVIDERS))
            .order_by(ApiKey.created_at.desc())
            .limit(1)
        )
        if row:
            try:
                return AgentConnection(row.provider, decrypt_key(row.ciphertext))
            except EncryptionError:
                await log.aerror("global credential undecryptable")

    fallback = get_settings().anthropic_api_key
    if fallback:
        return AgentConnection("anthropic", fallback)
    raise RuntimeError(
        "No agent connected: add an Anthropic key, Claude Code token, or Codex "
        "credential in the dashboard (or set ANTHROPIC_API_KEY)"
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


def check_budget(state_cost: float) -> None:
    """Raise BudgetExceeded if the per-scan cap is hit. Metered calls only."""
    if state_cost >= get_settings().scan_budget_usd:
        raise BudgetExceeded(
            f"scan budget ${get_settings().scan_budget_usd:.2f} exceeded (${state_cost:.4f} spent)"
        )
