"""Agent connection endpoints — detect installed CLIs, connect, test.

The backend runs on the user's own machine, where installed CLIs manage their
own logins (OS keyring, ~/.claude, ~/.codex). So "connecting" an agent usually
means storing the CLI_MANAGED marker — the CLI authenticates itself at call
time. Explicit tokens are only needed in Docker/CI, and are used automatically
when extractable from the standard credential files.
"""

import json
import shutil
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from agents.backends import CLI_MANAGED
from apps.api.routers.auth import read_session
from core.crypto import encrypt_key, fingerprint
from core.db.models import ApiKey, Installation
from core.db.session import get_session_factory

router = APIRouter(prefix="/api/agents", tags=["agents"])

CLAUDE_CREDENTIALS = Path.home() / ".claude" / ".credentials.json"
CODEX_AUTH = Path.home() / ".codex" / "auth.json"


def _session(request: Request) -> dict:
    return read_session(request)


def _claude_token() -> str | None:
    """Explicit OAuth token if the credentials file holds one (often it doesn't —
    Linux builds store the login in the OS keyring instead)."""
    try:
        data = json.loads(CLAUDE_CREDENTIALS.read_text())
        return (data.get("claudeAiOauth") or {}).get("accessToken")
    except Exception:
        return None


def _codex_logged_in() -> bool:
    return CODEX_AUTH.exists()


@router.get("/detect")
async def detect(_=Depends(_session)):
    """What's installed and authenticated on this machine?"""
    claude_cli = shutil.which("claude") is not None
    codex_cli = shutil.which("codex") is not None
    # The CLI manages its own login: presence of the binary + a login state we
    # can't always read directly (keyring). The test-connection button is the
    # authoritative check.
    return {
        "claude_code": {
            "cli_installed": claude_cli,
            "credentials_found": _claude_token() is not None or claude_cli,
            "connectable": claude_cli,
        },
        "codex": {
            "cli_installed": codex_cli,
            "credentials_found": _codex_logged_in(),
            "connectable": codex_cli and _codex_logged_in(),
        },
    }


class ConnectIn(BaseModel):
    installation_id: int | None = None  # None = global default connection
    provider: str  # 'claude_code' | 'codex'


def _credential_for(provider: str) -> str:
    """Best available credential: explicit token when extractable, else the
    CLI_MANAGED marker (the CLI authenticates itself)."""
    if provider == "claude_code":
        if shutil.which("claude") is None:
            raise HTTPException(400, "claude CLI not found on PATH")
        return _claude_token() or CLI_MANAGED
    if provider == "codex":
        if shutil.which("codex") is None:
            raise HTTPException(400, "codex CLI not found on PATH")
        if not _codex_logged_in():
            raise HTTPException(400, "Codex not logged in — run `codex login` first")
        return CLI_MANAGED
    raise HTTPException(400, "provider must be claude_code or codex")


@router.post("/connect", status_code=201)
async def connect(body: ConnectIn, _=Depends(_session)):
    credential = _credential_for(body.provider)

    async with get_session_factory()() as s:
        if body.installation_id is not None:
            inst = await s.get(Installation, body.installation_id)
            if not inst:
                raise HTTPException(404, "installation not found")
        existing = (
            await s.scalars(
                select(ApiKey).where(
                    ApiKey.installation_id.is_(None)
                    if body.installation_id is None
                    else ApiKey.installation_id == body.installation_id
                )
            )
        ).all()
        for row in existing:
            await s.delete(row)
        s.add(
            ApiKey(
                installation_id=body.installation_id,
                provider=body.provider,
                ciphertext=encrypt_key(credential),
                key_fingerprint="cli-managed"
                if credential == CLI_MANAGED
                else fingerprint(credential),
            )
        )
        await s.commit()
    return {
        "status": "connected",
        "provider": body.provider,
        "mode": "cli-managed" if credential == CLI_MANAGED else "token",
    }


@router.post("/test-connection")
async def test_connection(body: ConnectIn, _=Depends(_session)):
    """Prove the agent works: tiny prompt through the real backend."""
    import time

    from agents.llm import AgentConnection, make_cli_backend

    credential = _credential_for(body.provider)
    backend = make_cli_backend(AgentConnection(body.provider, credential))
    start = time.monotonic()
    try:
        resp = await backend.complete("Reply with exactly: ok", max_tokens=50)
        return {
            "ok": True,
            "latency_seconds": round(time.monotonic() - start, 1),
            "response_preview": resp.text[:100],
        }
    except (TimeoutError, RuntimeError, httpx.HTTPError) as e:
        return {"ok": False, "error": str(e)[:300]}
