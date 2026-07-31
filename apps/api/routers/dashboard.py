"""Dashboard REST API — scans, findings, fixes, PRs, stats, config.

Local-first: repos are local paths; PR actions go through the user's `gh` CLI;
configuration lives encrypted in app_config (langfuse keys, slack webhook).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from apps.api.routers.auth import read_session
from core.appconfig import get_config, set_config
from core.db.models import FindingRow, FixRow, PullRequestRow, Scan
from core.db.session import get_session_factory

router = APIRouter(prefix="/api", tags=["dashboard"])


def _session(request: Request) -> dict:
    return read_session(request)


# --- repos (local) ---


@router.get("/repos")
async def list_repos(_=Depends(_session)):
    """Local repos seen by the pipeline, with last scan time."""
    async with get_session_factory()() as s:
        rows = (
            await s.execute(
                select(Scan.repo_path, func.max(Scan.created_at).label("last_scan"))
                .group_by(Scan.repo_path)
                .order_by(func.max(Scan.created_at).desc())
            )
        ).all()
        return [
            {"path": r.repo_path, "last_scan": r.last_scan.isoformat() if r.last_scan else None}
            for r in rows
        ]


# --- scans / findings / fixes ---


@router.get("/scans")
async def list_scans(_=Depends(_session), repo: str | None = None, limit: int = 50):
    async with get_session_factory()() as s:
        q = select(Scan)
        if repo:
            q = q.where(Scan.repo_path == repo)
        q = q.order_by(Scan.created_at.desc()).limit(min(limit, 200))
        rows = (await s.scalars(q)).all()
        return [
            {
                "id": str(scan.id),
                "repo": scan.repo_path,
                "branch": scan.branch,
                "status": scan.status,
                "cost_usd": float(scan.llm_cost_usd or 0),
                "trace_url": scan.trace_url,
                "created_at": scan.created_at.isoformat() if scan.created_at else None,
                "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
            }
            for scan in rows
        ]


@router.get("/scans/{scan_id}")
async def scan_detail(scan_id: str, _=Depends(_session)):
    async with get_session_factory()() as s:
        scan = await s.scalar(select(Scan).where(Scan.id == uuid.UUID(scan_id)))
        if not scan:
            raise HTTPException(status_code=404, detail="scan not found")
        findings = (await s.scalars(select(FindingRow).where(FindingRow.scan_id == scan.id))).all()

        out_findings = []
        for f in findings:
            fix = await s.scalar(select(FixRow).where(FixRow.finding_id == f.id))
            pr = (
                await s.scalar(select(PullRequestRow).where(PullRequestRow.fix_id == fix.id))
                if fix
                else None
            )
            out_findings.append(
                {
                    "id": str(f.id),
                    "tool": f.tool,
                    "rule_id": f.rule_id,
                    "severity": f.severity,
                    "file_path": f.file_path,
                    "start_line": f.start_line,
                    "fix": (
                        {
                            "id": str(fix.id),
                            "status": fix.status,
                            "explanation": fix.explanation,
                            "attempts": fix.attempts,
                            "cost_usd": float(fix.cost_usd or 0),
                        }
                        if fix
                        else None
                    ),
                    "pr": (
                        {"number": pr.number, "url": pr.url, "state": pr.state, "branch": pr.branch}
                        if pr
                        else None
                    ),
                }
            )

        return {
            "id": str(scan.id),
            "repo": scan.repo_path,
            "branch": scan.branch,
            "status": scan.status,
            "error": scan.error,
            "cost_usd": float(scan.llm_cost_usd or 0),
            "trace_url": scan.trace_url,
            "created_at": scan.created_at.isoformat() if scan.created_at else None,
            "findings": out_findings,
        }


# --- stats ---


@router.get("/stats")
async def stats(_=Depends(_session)):
    async with get_session_factory()() as s:
        total_scans = await s.scalar(select(func.count(Scan.id)))
        total_findings = await s.scalar(select(func.count(FindingRow.id)))
        total_fixes = await s.scalar(select(func.count(FixRow.id)))
        open_prs = await s.scalar(
            select(func.count(PullRequestRow.id)).where(PullRequestRow.state == "open")
        )
        total_cost = await s.scalar(select(func.coalesce(func.sum(Scan.llm_cost_usd), 0)))
        tokens_in = await s.scalar(select(func.coalesce(func.sum(FixRow.tokens_in), 0)))
        tokens_out = await s.scalar(select(func.coalesce(func.sum(FixRow.tokens_out), 0)))
        return {
            "scans": total_scans or 0,
            "findings": total_findings or 0,
            "fixes": total_fixes or 0,
            "open_prs": open_prs or 0,
            "cost_usd": float(total_cost or 0),
            "tokens_in": tokens_in or 0,
            "tokens_out": tokens_out or 0,
        }


# --- approvals (HITL gate, via gh CLI) ---


@router.get("/approvals")
async def list_approvals(_=Depends(_session)):
    async with get_session_factory()() as s:
        rows = (
            await s.execute(
                select(PullRequestRow, FixRow, FindingRow)
                .join(FixRow, PullRequestRow.fix_id == FixRow.id)
                .join(FindingRow, FixRow.finding_id == FindingRow.id)
                .where(PullRequestRow.state == "open")
                .order_by(PullRequestRow.branch.desc())
            )
        ).all()
        return [
            {
                "fix_id": str(fix.id),
                "pr_number": pr.number,
                "pr_url": pr.url,
                "repo": pr.repo_path,
                "branch": pr.branch,
                "rule_id": finding.rule_id,
                "severity": finding.severity,
                "file_path": finding.file_path,
                "explanation": fix.explanation,
                "cost_usd": float(fix.cost_usd or 0),
            }
            for pr, fix, finding in rows
        ]


async def _gh(repo: str, *args: str) -> tuple[int, str]:
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        "gh",
        *args,
        cwd=repo,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode, (err or out).decode().strip()


@router.post("/fixes/{fix_id}/approve")
async def approve_fix(fix_id: str, _=Depends(_session)):
    return await _pr_action(fix_id, approve=True)


@router.post("/fixes/{fix_id}/reject")
async def reject_fix(fix_id: str, _=Depends(_session)):
    return await _pr_action(fix_id, approve=False)


async def _pr_action(fix_id: str, approve: bool) -> dict:
    async with get_session_factory()() as s:
        fix = await s.scalar(select(FixRow).where(FixRow.id == uuid.UUID(fix_id)))
        if not fix:
            raise HTTPException(status_code=404, detail="fix not found")
        pr = await s.scalar(select(PullRequestRow).where(PullRequestRow.fix_id == fix.id))
        if not pr:
            raise HTTPException(status_code=404, detail="no PR for this fix")

    if pr.number:
        if approve:
            rc, out = await _gh(pr.repo_path, "pr", "merge", str(pr.number), "--squash")
        else:
            rc, out = await _gh(pr.repo_path, "pr", "close", str(pr.number))
        if rc != 0:
            raise HTTPException(500, f"gh failed: {out[:300]}")
    # Branch-only fix (no PR): approve = merge branch into current; reject = delete branch
    else:
        import asyncio

        if approve:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "merge",
                "--squash",
                pr.branch,
                cwd=pr.repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        else:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "branch",
                "-D",
                pr.branch,
                cwd=pr.repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

    pr.state = "merged" if approve else "closed"
    async with get_session_factory()() as s:
        await s.merge(pr)
        await s.commit()
    return {"status": pr.state, "pr": pr.url or pr.branch}


# --- config (langfuse, slack) ---


class ConfigIn(BaseModel):
    key: str
    value: str


_ALLOWED_CONFIG_KEYS = {
    "langfuse_host",
    "langfuse_public_key",
    "langfuse_secret_key",
    "slack_webhook_url",
}


@router.get("/config")
async def get_config_values(_=Depends(_session)):
    """Which config values are set (never the values themselves)."""
    return {key: bool(await get_config(key)) for key in sorted(_ALLOWED_CONFIG_KEYS)}


@router.post("/config")
async def set_config_value(body: ConfigIn, _=Depends(_session)):
    if body.key not in _ALLOWED_CONFIG_KEYS:
        raise HTTPException(400, f"key must be one of {sorted(_ALLOWED_CONFIG_KEYS)}")
    await set_config(body.key, body.value)
    return {"status": "saved", "key": body.key}


class LangfuseTestIn(BaseModel):
    host: str
    public_key: str
    secret_key: str


@router.post("/config/test-langfuse")
async def test_langfuse(body: LangfuseTestIn, _=Depends(_session)):
    """Validate Langfuse credentials before saving — like the agent test button."""
    import asyncio

    def _check() -> tuple[bool, str]:
        try:
            from langfuse import Langfuse

            client = Langfuse(
                public_key=body.public_key,
                secret_key=body.secret_key,
                host=body.host.rstrip("/"),
            )
            ok = client.auth_check()
            client.flush()
            return (True, "connected") if ok else (False, "authentication failed — check the keys")
        except Exception as e:
            return False, str(e)[:200]

    ok, detail = await asyncio.to_thread(_check)
    if not ok:
        raise HTTPException(400, detail)
    return {"status": "ok", "detail": detail}
