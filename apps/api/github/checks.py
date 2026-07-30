"""Check-run helpers — one `gitguardian/scan` check per commit.

Conclusions:
  success — clean scan, or all fixes merged... Phase 1: clean scan only
  neutral — findings exist and a fix PR was opened (the signal lives on the PR)
  failure — pipeline error
Annotations surface findings inline in the Files Changed tab.
"""

from typing import Any

from apps.api.github.client import GitHubClient
from core.schemas import Finding

CHECK_NAME = "gitguardian/scan"
MAX_ANNOTATIONS = 50  # GitHub hard limit per request


def _annotation_level(severity: str) -> str:
    return {"critical": "failure", "high": "failure", "medium": "warning", "low": "notice"}.get(
        severity, "warning"
    )


async def create_check(client: GitHubClient, repo: str, sha: str) -> int:
    data = await client.post(
        f"/repos/{repo}/check-runs",
        json={"name": CHECK_NAME, "head_sha": sha, "status": "queued"},
    )
    return data["id"]


async def update_check(
    client: GitHubClient,
    repo: str,
    check_id: int,
    *,
    status: str | None = None,
    conclusion: str | None = None,
    title: str | None = None,
    summary: str | None = None,
    findings: list[Finding] | None = None,
) -> None:
    payload: dict[str, Any] = {}
    if status:
        payload["status"] = status
    if conclusion:
        payload["conclusion"] = conclusion
    if title or summary:
        payload["output"] = {"title": title or CHECK_NAME, "summary": summary or ""}
    if findings:
        payload.setdefault("output", {"title": title or CHECK_NAME, "summary": summary or ""})
        payload["output"]["annotations"] = [
            {
                "path": f.file_path,
                "start_line": f.start_line,
                "end_line": f.end_line or f.start_line,
                "annotation_level": _annotation_level(f.severity),
                "message": f"{f.rule_id}: {f.message}"[:64000],
                "title": f.rule_id[:255],
            }
            for f in findings[:MAX_ANNOTATIONS]
        ]
    await client.patch(f"/repos/{repo}/check-runs/{check_id}", json=payload)
