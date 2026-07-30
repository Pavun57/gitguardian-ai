"""arq worker — dequeues scan jobs and drives the LangGraph pipeline.

State durability: the graph runs with an in-memory saver per invocation in
Phase 1; the scans/findings/fixes tables are the audit trail. (Postgres
checkpointer is a one-line upgrade if cross-restart resume is needed.)
"""

import shutil
import uuid

from arq.connections import RedisSettings
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import select

from agents.graph import build_graph
from agents.router.node import SkipScan
from apps.api.github.checks import create_check, update_check
from apps.api.github.client import GitHubClient
from core.config import get_settings
from core.db.models import Repository, Scan
from core.db.session import get_session_factory
from core.logging import configure_logging, get_logger

log = get_logger("worker")


async def run_scan(ctx: dict, scan_id: str) -> None:
    async with get_session_factory()() as session:
        scan = await session.scalar(select(Scan).where(Scan.id == uuid.UUID(scan_id)))
        if not scan:
            await log.aerror("scan not found", scan_id=scan_id)
            return
        repo = await session.scalar(select(Repository).where(Repository.id == scan.repository_id))
        installation_id = repo.installation_id if repo else None
        repo_full_name = repo.full_name if repo else ""
        scan.status = "running"
        await session.commit()
        commit_sha, ref = scan.commit_sha, scan.ref

    if not installation_id:
        await log.aerror("no installation for scan", scan_id=scan_id)
        return

    check_run_id = None
    try:
        async with GitHubClient(installation_id) as client:
            check_run_id = await create_check(client, repo_full_name, commit_sha)
            await update_check(client, repo_full_name, check_run_id, status="in_progress")
    except Exception as e:
        await log.awarning("check-run create failed (continuing)", error=str(e)[:300])

    graph = build_graph(checkpointer=MemorySaver())
    initial = {
        "scan_id": scan_id,
        "installation_id": installation_id,
        "repo_full_name": repo_full_name,
        "commit_sha": commit_sha,
        "ref": ref,
        "check_run_id": check_run_id,
        "findings": [],
        "findings_index": 0,
        "fix_attempts": 0,
        "prs": [],
        "events": [],
        "llm_cost_usd": 0.0,
        "llm_input_tokens": 0,
        "llm_output_tokens": 0,
    }
    config = {"configurable": {"thread_id": scan_id}, "recursion_limit": 60}

    workdir = None
    try:
        final = await graph.ainvoke(initial, config=config)
        workdir = final.get("workdir")
        await log.ainfo(
            "scan finished",
            scan_id=scan_id,
            prs=len(final.get("prs", [])),
            cost=final.get("llm_cost_usd", 0),
        )
    except SkipScan as e:
        await log.ainfo("scan skipped", scan_id=scan_id, reason=e.reason)
        await _mark(scan_id, "completed")
        if check_run_id:
            await _safe_check(
                installation_id, repo_full_name, check_run_id, "neutral", f"Skipped: {e.reason}"
            )
    except Exception as e:
        await log.aerror("scan failed", scan_id=scan_id, error=str(e)[:1000])
        await _mark(scan_id, "failed", str(e)[:1000])
        if check_run_id:
            await _safe_check(
                installation_id,
                repo_full_name,
                check_run_id,
                "failure",
                f"Pipeline error: {str(e)[:500]}",
            )
        raise  # let arq record the failure
    finally:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)


async def _mark(scan_id: str, status: str, error: str | None = None) -> None:
    from datetime import UTC, datetime

    async with get_session_factory()() as session:
        scan = await session.scalar(select(Scan).where(Scan.id == uuid.UUID(scan_id)))
        if scan:
            scan.status = status
            scan.error = error
            scan.finished_at = datetime.now(UTC)
        await session.commit()


async def _safe_check(installation_id, repo, check_id, conclusion, summary) -> None:
    try:
        async with GitHubClient(installation_id) as client:
            await update_check(
                client, repo, check_id, status="completed", conclusion=conclusion, summary=summary
            )
    except Exception as e:
        await log.awarning("check-run update failed (swallowed)", error=str(e)[:200])


async def startup(ctx: dict) -> None:
    configure_logging()
    await log.ainfo("worker started")


def _redis_settings() -> RedisSettings:
    from urllib.parse import urlparse

    parsed = urlparse(get_settings().redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int((parsed.path or "/0").lstrip("/")),
    )


class WorkerSettings:
    functions = [run_scan]
    on_startup = startup
    redis_settings = _redis_settings()
    max_jobs = 4
    job_timeout = 900  # 15 min per scan
