"""Dashboard REST API — repos, scans, findings, fixes, PRs, BYOK keys, stats.

All routes require a dashboard session. Responses are shaped for the Next.js
frontend; nothing here exposes decrypted keys or secrets (fingerprints only).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from apps.api.routers.auth import read_session
from core.crypto import encrypt_key, fingerprint
from core.db.models import (
    ApiKey,
    FindingRow,
    FixRow,
    Installation,
    PullRequestRow,
    Repository,
    Scan,
)
from core.db.session import get_session_factory

router = APIRouter(prefix="/api", tags=["dashboard"])


def _session(request: Request) -> dict:
    return read_session(request)


# --- GitHub App configuration (setup wizard) ---


class GitHubConfigIn(BaseModel):
    app_id: str | None = None
    app_slug: str | None = None
    webhook_secret: str | None = None
    private_key: str | None = None  # full PEM contents


@router.get("/github/config")
async def get_github_config(_=Depends(_session)):
    """Setup status: which credentials are set, plus the URLs to paste into GitHub."""
    from core.appconfig import config_status, get_config
    from core.config import get_settings

    status = await config_status()
    slug = await get_config("github_app_slug")
    s = get_settings()
    return {
        "configured": status,
        "all_set": all(status.values()),
        "app_slug": slug,
        "webhook_url": f"{s.api_base_url}/webhooks/github",
        "setup_url": f"{s.dashboard_url}/settings",
        "manifest_url": f"{s.api_base_url}/api/github/manifest",
    }


@router.post("/github/config")
async def set_github_config(body: GitHubConfigIn, _=Depends(_session)):
    from core.appconfig import set_config

    if body.app_id:
        await set_config("github_app_id", body.app_id)
    if body.app_slug:
        await set_config("github_app_slug", body.app_slug)
    if body.webhook_secret:
        await set_config("github_webhook_secret", body.webhook_secret)
    if body.private_key:
        if "PRIVATE KEY" not in body.private_key:
            raise HTTPException(400, "that doesn't look like a PEM private key")
        await set_config("github_app_private_key", body.private_key)
    return {"status": "saved"}


@router.get("/github/manifest")
async def github_app_manifest(_=Depends(_session)):
    """GitHub App Manifest flow: pre-fills the entire app registration form.

    POST this manifest to https://github.com/settings/apps/new (the UI does it
    via a form) — GitHub creates the app with correct permissions, events, and
    URLs in one click instead of manual form filling.
    """
    from core.config import get_settings

    s = get_settings()
    return {
        "name": "GitGuardian AI (dev)",
        "url": s.dashboard_url,
        "hook_attributes": {"url": f"{s.api_base_url}/webhooks/github", "active": True},
        "redirect_url": f"{s.dashboard_url}/settings",
        "callback_urls": [f"{s.api_base_url}/auth/github/callback"],
        "public": False,
        "default_permissions": {
            "contents": "write",
            "pull_requests": "write",
            "checks": "write",
            "metadata": "read",
        },
        "default_events": ["push", "installation", "installation_repositories"],
    }


# --- repos / installations ---


@router.get("/github/connect-url")
async def github_connect_url(_=Depends(_session)):
    """Where to send the user to install the GitHub App (GitHub-hosted OAuth-style flow)."""
    from core.config import get_settings

    slug = get_settings().github_app_slug
    if not slug:
        raise HTTPException(status_code=500, detail="GITHUB_APP_SLUG not configured")
    return {"url": f"https://github.com/apps/{slug}/installations/new"}


@router.post("/github/sync")
async def sync_installations(_=Depends(_session)):
    """Pull installations + repos from the GitHub API and RECONCILE the DB.

    GitHub is the source of truth: installations removed on GitHub are marked
    uninstalled, and repos no longer granted to the app are deactivated.
    Resilience path: the settings page doesn't depend on the installation
    webhook having been delivered (tunnel down at install time, etc.).
    """
    from datetime import UTC, datetime

    import httpx

    from apps.api.github.auth import app_jwt, installation_token
    from core.config import get_settings

    base = get_settings().github_api_base
    synced = []
    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.get(
            f"{base}/app/installations",
            headers={
                "Authorization": f"Bearer {await app_jwt()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        resp.raise_for_status()
        installations = resp.json()
        remote_inst_ids = {i["id"] for i in installations}

        async with get_session_factory()() as s:
            # Installations deleted on GitHub → mark uninstalled locally
            local_insts = (
                await s.scalars(select(Installation).where(Installation.uninstalled_at.is_(None)))
            ).all()
            for local in local_insts:
                if local.id not in remote_inst_ids:
                    local.uninstalled_at = datetime.now(UTC)
                    local_repos = (
                        await s.scalars(
                            select(Repository).where(Repository.installation_id == local.id)
                        )
                    ).all()
                    for r in local_repos:
                        r.is_active = False

            for inst in installations:
                inst_id = inst["id"]
                account = (inst.get("account") or {}).get("login", "")
                existing = await s.get(Installation, inst_id)
                if existing:
                    existing.account_login = account
                    existing.uninstalled_at = None
                else:
                    s.add(Installation(id=inst_id, account_login=account))

                token = await installation_token(inst_id, http)
                repos_resp = await http.get(
                    f"{base}/installation/repositories",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                repos_resp.raise_for_status()
                remote_repos = repos_resp.json().get("repositories", [])
                remote_repo_ids = {r["id"] for r in remote_repos}

                # Repos removed from the installation → deactivate
                local_repos = (
                    await s.scalars(select(Repository).where(Repository.installation_id == inst_id))
                ).all()
                for r in local_repos:
                    r.is_active = r.id in remote_repo_ids

                for r in remote_repos:
                    existing_repo = await s.get(Repository, r["id"])
                    if existing_repo:
                        existing_repo.is_active = True
                        existing_repo.default_branch = r.get("default_branch") or "main"
                    else:
                        s.add(
                            Repository(
                                id=r["id"],
                                installation_id=inst_id,
                                full_name=r["full_name"],
                                default_branch=r.get("default_branch") or "main",
                            )
                        )
                synced.append({"id": inst_id, "account": account, "repos": len(remote_repos)})
            await s.commit()
    return {"synced": synced}


@router.get("/installations")
async def list_installations(_=Depends(_session)):
    """Installations known via webhook events — populated automatically on install."""
    async with get_session_factory()() as s:
        rows = (
            await s.scalars(select(Installation).where(Installation.uninstalled_at.is_(None)))
        ).all()
        return [{"id": r.id, "account": r.account_login} for r in rows]


@router.get("/repos")
async def list_repos(_=Depends(_session)):
    async with get_session_factory()() as s:
        rows = (await s.scalars(select(Repository).where(Repository.is_active))).all()
        return [
            {"id": r.id, "full_name": r.full_name, "default_branch": r.default_branch} for r in rows
        ]


# --- scans / findings / fixes ---


@router.get("/scans")
async def list_scans(_=Depends(_session), repo: str | None = None, limit: int = 50):
    async with get_session_factory()() as s:
        q = select(Scan, Repository.full_name).join(Repository, Scan.repository_id == Repository.id)
        if repo:
            q = q.where(Repository.full_name == repo)
        q = q.order_by(Scan.created_at.desc()).limit(min(limit, 200))
        rows = (await s.execute(q)).all()
        return [
            {
                "id": str(scan.id),
                "repo": full_name,
                "commit_sha": scan.commit_sha[:7],
                "ref": scan.ref,
                "status": scan.status,
                "cost_usd": float(scan.llm_cost_usd or 0),
                "created_at": scan.created_at.isoformat() if scan.created_at else None,
                "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
            }
            for scan, full_name in rows
        ]


@router.get("/scans/{scan_id}")
async def scan_detail(scan_id: str, _=Depends(_session)):
    async with get_session_factory()() as s:
        scan = await s.scalar(select(Scan).where(Scan.id == uuid.UUID(scan_id)))
        if not scan:
            raise HTTPException(status_code=404, detail="scan not found")
        repo = await s.scalar(select(Repository).where(Repository.id == scan.repository_id))
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
                    "pr": ({"number": pr.number, "url": pr.url, "state": pr.state} if pr else None),
                }
            )

        return {
            "id": str(scan.id),
            "repo": repo.full_name if repo else "?",
            "commit_sha": scan.commit_sha,
            "status": scan.status,
            "error": scan.error,
            "cost_usd": float(scan.llm_cost_usd or 0),
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
        return {
            "scans": total_scans or 0,
            "findings": total_findings or 0,
            "fixes": total_fixes or 0,
            "open_prs": open_prs or 0,
            "cost_usd": float(total_cost or 0),
        }


# --- BYOK keys ---


class KeyIn(BaseModel):
    installation_id: int
    provider: str = "anthropic"  # 'anthropic' | 'claude_code' | 'codex'
    credential: str


_CREDENTIAL_HINTS = {
    "anthropic": ("sk-ant-", "sk-"),
    "claude_code": ("sk-ant-oat",),  # OAuth tokens from `claude setup-token`
    "codex": ("sk-", "{"),  # OpenAI key or ChatGPT auth.json
}


@router.get("/keys")
async def list_keys(_=Depends(_session)):
    """Fingerprints only — decrypted keys never leave the backend."""
    async with get_session_factory()() as s:
        rows = (await s.scalars(select(ApiKey))).all()
        return [
            {
                "installation_id": r.installation_id,
                "provider": r.provider,
                "fingerprint": r.key_fingerprint,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


@router.post("/keys", status_code=201)
async def set_key(body: KeyIn, _=Depends(_session)):
    if body.provider not in _CREDENTIAL_HINTS:
        valid = list(_CREDENTIAL_HINTS)
        raise HTTPException(status_code=400, detail=f"provider must be one of {valid}")
    if not body.credential.strip().startswith(_CREDENTIAL_HINTS[body.provider]):
        raise HTTPException(
            status_code=400, detail=f"credential doesn't look like a {body.provider} credential"
        )
    async with get_session_factory()() as s:
        inst = await s.get(Installation, body.installation_id)
        if not inst:
            raise HTTPException(status_code=404, detail="installation not found")
        # One agent connection per installation: replace any existing
        existing = (
            await s.scalars(select(ApiKey).where(ApiKey.installation_id == body.installation_id))
        ).all()
        for row in existing:
            await s.delete(row)
        s.add(
            ApiKey(
                installation_id=body.installation_id,
                provider=body.provider,
                ciphertext=encrypt_key(body.credential),
                key_fingerprint=fingerprint(body.credential),
            )
        )
        await s.commit()
    return {
        "status": "stored",
        "provider": body.provider,
        "fingerprint": fingerprint(body.credential),
    }


@router.delete("/keys/{installation_id}", status_code=204)
async def delete_key(installation_id: str, _=Depends(_session)):
    inst_id = None if installation_id == "global" else int(installation_id)
    async with get_session_factory()() as s:
        rows = (
            await s.scalars(
                select(ApiKey).where(
                    ApiKey.installation_id.is_(None)
                    if inst_id is None
                    else ApiKey.installation_id == inst_id
                )
            )
        ).all()
        for r in rows:
            await s.delete(r)
        await s.commit()


# --- Slack notifications ---


class SlackIn(BaseModel):
    installation_id: int
    webhook_url: str


@router.post("/slack", status_code=201)
async def set_slack(body: SlackIn, _=Depends(_session)):
    if not body.webhook_url.startswith("https://hooks.slack.com/"):
        raise HTTPException(status_code=400, detail="not a Slack webhook URL")
    async with get_session_factory()() as s:
        inst = await s.get(Installation, body.installation_id)
        if not inst:
            raise HTTPException(status_code=404, detail="installation not found")
        inst.slack_webhook_ciphertext = encrypt_key(body.webhook_url)
        await s.commit()
    return {"status": "stored"}


@router.get("/slack/{installation_id}")
async def get_slack(installation_id: int, _=Depends(_session)):
    async with get_session_factory()() as s:
        inst = await s.get(Installation, installation_id)
        if not inst:
            raise HTTPException(status_code=404, detail="installation not found")
        return {"configured": inst.slack_webhook_ciphertext is not None}


@router.delete("/slack/{installation_id}", status_code=204)
async def delete_slack(installation_id: int, _=Depends(_session)):
    async with get_session_factory()() as s:
        inst = await s.get(Installation, installation_id)
        if inst:
            inst.slack_webhook_ciphertext = None
            await s.commit()


# --- approvals (HITL gate) ---


@router.get("/approvals")
async def list_approvals(_=Depends(_session)):
    """Fixes with open PRs — the HITL approval queue."""
    async with get_session_factory()() as s:
        rows = (
            await s.execute(
                select(PullRequestRow, FixRow, FindingRow)
                .join(FixRow, PullRequestRow.fix_id == FixRow.id)
                .join(FindingRow, FixRow.finding_id == FindingRow.id)
                .where(PullRequestRow.state == "open")
                .order_by(PullRequestRow.number.desc())
            )
        ).all()
        return [
            {
                "fix_id": str(fix.id),
                "pr_number": pr.number,
                "pr_url": pr.url,
                "repo": pr.repo_full_name,
                "branch": pr.branch,
                "rule_id": finding.rule_id,
                "severity": finding.severity,
                "file_path": finding.file_path,
                "explanation": fix.explanation,
                "fix_status": fix.status,
                "cost_usd": float(fix.cost_usd or 0),
            }
            for pr, fix, finding in rows
        ]


@router.post("/fixes/{fix_id}/approve")
async def approve_fix(fix_id: str, _=Depends(_session)):
    """Merge the fix's PR — the human approval action."""
    return await _pr_action(fix_id, approve=True)


@router.post("/fixes/{fix_id}/reject")
async def reject_fix(fix_id: str, _=Depends(_session)):
    """Close the fix's PR — the human rejection action."""
    return await _pr_action(fix_id, approve=False)


async def _pr_action(fix_id: str, approve: bool) -> dict:
    from apps.api.github.client import GitHubClient

    async with get_session_factory()() as s:
        fix = await s.scalar(select(FixRow).where(FixRow.id == uuid.UUID(fix_id)))
        if not fix:
            raise HTTPException(status_code=404, detail="fix not found")
        pr = await s.scalar(select(PullRequestRow).where(PullRequestRow.fix_id == fix.id))
        if not pr:
            raise HTTPException(status_code=404, detail="no PR for this fix")
        repo = await s.scalar(select(Repository).where(Repository.full_name == pr.repo_full_name))

    async with GitHubClient(repo.installation_id) as client:
        if approve:
            await client._request(
                "PUT",
                f"/repos/{pr.repo_full_name}/pulls/{pr.number}/merge",
                json={"merge_method": "squash"},
            )
            pr.state = "merged"
        else:
            await client._request(
                "PATCH",
                f"/repos/{pr.repo_full_name}/pulls/{pr.number}",
                json={"state": "closed"},
            )
            pr.state = "closed"

    async with get_session_factory()() as s:
        await s.merge(pr)
        await s.commit()
    return {"status": pr.state, "pr": pr.url}
