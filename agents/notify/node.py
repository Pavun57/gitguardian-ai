"""Notify node — final check-run update with annotations + Slack delivery.

Notification must never fail the scan: every error here is logged and swallowed.
"""

from agents.notify.slack import send_slack
from agents.state import GuardianState
from apps.api.github.checks import update_check
from apps.api.github.client import GitHubClient
from core.logging import get_logger

log = get_logger("notify")


async def notify_node(state: GuardianState) -> dict:
    await send_slack(state)
    check_id = state.get("check_run_id")
    if not check_id:
        return {}

    prs = state.get("prs", [])
    findings = state.get("findings", [])
    cost = state.get("llm_cost_usd", 0.0)

    try:
        async with GitHubClient(state["installation_id"]) as client:
            if not findings:
                await update_check(
                    client,
                    state["repo_full_name"],
                    check_id,
                    status="completed",
                    conclusion="success",
                    title="GitGuardian: clean",
                    summary="No security findings (semgrep + gitleaks).",
                )
            elif prs:
                lines = "\n".join(f"- #{p.number} [{p.branch}]({p.url})" for p in prs)
                await update_check(
                    client,
                    state["repo_full_name"],
                    check_id,
                    status="completed",
                    conclusion="neutral",
                    title=f"GitGuardian: {len(findings)} finding(s), {len(prs)} fix PR(s) opened",
                    summary=f"Fix PRs awaiting review:\n{lines}\n\nLLM cost: ${cost:.4f}",
                    findings=findings,
                )
            else:
                await update_check(
                    client,
                    state["repo_full_name"],
                    check_id,
                    status="completed",
                    conclusion="neutral",
                    title=f"GitGuardian: {len(findings)} finding(s) need human attention",
                    summary=(
                        "Findings detected but no automatic fix was possible "
                        "(low confidence, budget cap, or tests kept failing).\n\n"
                        f"LLM cost: ${cost:.4f}"
                    ),
                    findings=findings,
                )
        await log.ainfo("check-run updated", scan_id=state["scan_id"])
    except Exception as e:
        await log.aerror("notify failed (swallowed)", error=str(e)[:300])

    return {"events": ["notify: check-run updated"]}
