"""LLM access: BYOK resolution, model factory, cost tracking.

Key resolution order: installation's encrypted key in Postgres → env fallback.
All model calls go through `tracked_chat` so per-scan spend is accumulated in
state and the budget cap is enforceable before every call.
"""

from sqlalchemy import select

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


class BudgetExceeded(Exception):
    pass


async def resolve_api_key(installation_id: int | None) -> str:
    """BYOK: installation's key first, env var as Phase 1 fallback."""
    if installation_id is not None:
        async with get_session_factory()() as session:
            row = await session.scalar(
                select(ApiKey)
                .where(ApiKey.installation_id == installation_id, ApiKey.provider == "anthropic")
                .order_by(ApiKey.created_at.desc())
                .limit(1)
            )
            if row:
                try:
                    return decrypt_key(row.ciphertext)
                except EncryptionError:
                    await log.aerror("stored key undecryptable", installation_id=installation_id)
    fallback = get_settings().anthropic_api_key
    if not fallback:
        raise RuntimeError(
            "No Anthropic key available: no BYOK key for installation and ANTHROPIC_API_KEY unset"
        )
    return fallback


def make_chat_model(model: str, api_key: str, temperature: float = 0.2):
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=model, api_key=api_key, temperature=temperature, max_tokens=8192)


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = _PRICING.get(model, (3.00, 15.00))
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


def check_budget(state_cost: float) -> None:
    """Raise BudgetExceeded if the per-scan cap is hit. Call before every LLM call."""
    if state_cost >= get_settings().scan_budget_usd:
        raise BudgetExceeded(
            f"scan budget ${get_settings().scan_budget_usd:.2f} exceeded (${state_cost:.4f} spent)"
        )
