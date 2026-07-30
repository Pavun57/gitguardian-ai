"""Runtime config resolution: DB (UI-entered, encrypted) → env fallback.

Used for GitHub App credentials so a fresh install can be configured entirely
from the dashboard — no .env editing.
"""

from core.config import get_settings
from core.crypto import EncryptionError, decrypt_key, encrypt_key
from core.db.models import AppConfig
from core.db.session import get_session_factory

CONFIG_KEYS = (
    "github_app_id",
    "github_app_slug",
    "github_webhook_secret",
    "github_app_private_key",
    "smee_channel_url",
)


async def get_config(key: str) -> str:
    """DB value first, env fallback, else empty string. DB errors fall back to env."""
    try:
        async with get_session_factory()() as s:
            row = await s.get(AppConfig, key)
            if row:
                try:
                    return decrypt_key(row.ciphertext)
                except EncryptionError:
                    pass  # undecryptable row — fall through to env
    except Exception:  # noqa: S110 - intentional: env is the fallback path
        pass  # DB unavailable — env fallback
    if key == "github_app_private_key":
        import asyncio
        from pathlib import Path

        try:
            return await asyncio.to_thread(
                Path(get_settings().github_app_private_key_path).read_text
            )
        except OSError:
            return ""
    return getattr(get_settings(), key, "") or ""


async def set_config(key: str, value: str) -> None:
    async with get_session_factory()() as s:
        row = await s.get(AppConfig, key)
        if row:
            row.ciphertext = encrypt_key(value)
        else:
            s.add(AppConfig(key=key, ciphertext=encrypt_key(value)))
        await s.commit()


async def config_status() -> dict[str, bool]:
    """Which config keys are set (DB or env) — for the setup wizard."""
    out = {}
    for key in CONFIG_KEYS:
        out[key] = bool(await get_config(key))
    return out
