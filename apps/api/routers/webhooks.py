"""GitHub webhook receiver.

Contract: ACK in <200ms. Verify signature, dedup delivery, persist a queued Scan,
enqueue the job — nothing more. All heavy work happens in the arq worker.
"""

import redis.asyncio as aioredis
from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from apps.api.github.verify import SignatureError, verify_signature
from apps.api.queue import enqueue_scan, is_duplicate_delivery
from core.config import get_settings
from core.db.models import Installation, Repository, Scan
from core.db.session import get_session_factory
from core.logging import get_logger

router = APIRouter()
log = get_logger("webhooks")

_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(get_settings().redis_url)
    return _redis


@router.post("/webhooks/github", status_code=202, response_model=None)
async def github_webhook(request: Request):
    body = await request.body()

    try:
        await verify_signature(body, request.headers.get("X-Hub-Signature-256"))
    except SignatureError as e:
        await log.awarning("webhook rejected", reason=str(e))
        return Response(status_code=401)

    event = request.headers.get("X-GitHub-Event", "")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    redis = await _get_redis()

    if delivery_id and await is_duplicate_delivery(redis, delivery_id):
        await log.ainfo("duplicate delivery ignored", delivery_id=delivery_id, event_type=event)
        return {"status": "duplicate"}

    payload = await request.json()

    if event == "push":
        return await _handle_push(payload)
    if event in ("installation", "installation_repositories"):
        await _handle_installation(event, payload)
        return {"status": "ok"}

    await log.ainfo("event ignored", event_type=event)
    return {"status": "ignored"}


async def _handle_push(payload: dict) -> dict:
    repo = payload.get("repository", {})
    repo_id = repo.get("id")
    ref = payload.get("ref", "")
    head = payload.get("head_commit") or {}
    sha = head.get("id") or payload.get("after", "")

    if not repo_id or not sha:
        await log.awarning("malformed push payload")
        return {"status": "ignored"}

    async with get_session_factory()() as session:
        # Only scan repos that were provisioned via an installation event.
        tracked = await session.scalar(select(Repository.id).where(Repository.id == repo_id))
        if tracked is None:
            await log.ainfo("push for untracked repo", repo=repo.get("full_name"))
            return {"status": "untracked"}

        scan = Scan(repository_id=repo_id, commit_sha=sha, ref=ref, status="queued")
        session.add(scan)
        await session.commit()
        scan_id = str(scan.id)

    await enqueue_scan(scan_id)
    await log.ainfo("scan queued", scan_id=scan_id, repo=repo.get("full_name"), sha=sha[:7])
    return {"status": "queued", "scan_id": scan_id}


async def _handle_installation(event: str, payload: dict) -> None:
    action = payload.get("action", "")
    inst = payload.get("installation", {})
    inst_id = inst.get("id")
    account = (inst.get("account") or {}).get("login", "")
    if not inst_id:
        return

    repos = payload.get("repositories") or payload.get("repositories_added") or []
    removed = payload.get("repositories_removed") or []

    async with get_session_factory()() as session:
        if action == "deleted":
            row = await session.get(Installation, inst_id)
            if row:
                from datetime import UTC, datetime

                row.uninstalled_at = datetime.now(UTC)
            await session.commit()
            return

        await session.merge(Installation(id=inst_id, account_login=account))
        for r in repos:
            await session.merge(
                Repository(
                    id=r["id"],
                    installation_id=inst_id,
                    full_name=r["full_name"],
                    default_branch=(r.get("default_branch") or "main"),
                )
            )
        for r in removed:
            row = await session.get(Repository, r["id"])
            if row:
                row.is_active = False
        await session.commit()

    await log.ainfo(
        "installation event processed", event_type=event, action=action, installation=inst_id
    )
