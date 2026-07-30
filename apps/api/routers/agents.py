"""Agent connection endpoints — detect installed CLIs, connect, test.

Because the backend runs on the user's own machine (local dev / self-hosted),
it can discover Claude Code and Codex credentials directly from their standard
config locations instead of asking the user to paste anything:

  Claude Code: `claude` CLI on PATH + ~/.claude/.credentials.json (OAuth token)
  Codex:       `codex` CLI on PATH + ~/.codex/auth.json (ChatGPT auth)

/test-connection runs a tiny prompt through the backend to prove it works.
"""

import json
import shutil
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

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
    try:
        data = json.loads(CLAUDE_CREDENTIALS.read_text())
        return (data.get("claudeAiOauth") or {}).get("accessToken")
    except Exception:
        return None


def _codex_auth() -> str | None:
    try:
        return CODEX_AUTH.read_text() if CODEX_AUTH.exists() else None
    except Exception:
        return None


@router.get("/detect")
async def detect(_=Depends(_session)):
    """What's installed and authenticated on this machine?"""
    claude_cli = shutil.which("claude") is not None
    codex_cli = shutil.which("codex") is not None
    claude_token = _claude_token()
    codex_auth = _codex_auth()
    return {
        "claude_code": {
            "cli_installed": claude_cli,
            "credentials_found": claude_token is not None,
            "connectable": claude_cli and claude_token is not None,
        },
        "codex": {
            "cli_installed": codex_cli,
            "credentials_found": codex_auth is not None,
            "connectable": codex_cli and codex_auth is not None,
        },
    }


class ConnectIn(BaseModel):
    installation_id: int
    provider: str  # 'claude_code' | 'codex'


@router.post("/connect", status_code=201)
async def connect(body: ConnectIn, _=Depends(_session)):
    """Read the local credential for the chosen agent and store it encrypted."""
    if body.provider == "claude_code":
        credential = _claude_token()
        if not credential:
            raise HTTPException(
                400, "Claude Code credentials not found — run `claude` and log in first"
            )
    elif body.provider == "codex":
        credential = _codex_auth()
        if not credential:
            raise HTTPException(
                400, "Codex credentials not found — run `codex login` first"
            )
    else:
        raise HTTPException(400, "provider must be claude_code or codex")

    async with get_session_factory()() as s:
        inst = await s.get(Installation, body.installation_id)
        if not inst:
            raise HTTPException(404, "installation not found")
        existing = (
            await s.scalars(select(ApiKey).where(ApiKey.installation_id == body.installation_id))
        ).all()
        for row in existing:
            await s.delete(row)
        s.add(
            ApiKey(
                installation_id=body.installation_id,
                provider=body.provider,
                ciphertext=encrypt_key(credential),
                key_fingerprint=fingerprint(credential),
            )
        )
        await s.commit()
    return {
        "status": "connected",
        "provider": body.provider,
        "fingerprint": fingerprint(credential),
    }


@router.post("/test-connection")
async def test_connection(body: ConnectIn, _=Depends(_session)):
    """Prove the agent works: tiny prompt through the real backend."""
    import time

    from agents.llm import AgentConnection, make_cli_backend

    if body.provider == "claude_code":
        credential = _claude_token()
        prompt = "Reply with exactly: ok"
    elif body.provider == "codex":
        credential = _codex_auth()
        prompt = "Reply with exactly: ok"
    else:
        raise HTTPException(400, "provider must be claude_code or codex")
    if not credential:
        raise HTTPException(400, f"no local credentials for {body.provider}")

    backend = make_cli_backend(AgentConnection(body.provider, credential))
    start = time.monotonic()
    try:
        resp = await backend.complete(prompt, max_tokens=50)
        return {
            "ok": True,
            "latency_seconds": round(time.monotonic() - start, 1),
            "response_preview": resp.text[:100],
        }
    except (TimeoutError, RuntimeError, httpx.HTTPError) as e:
        return {"ok": False, "error": str(e)[:300]}
