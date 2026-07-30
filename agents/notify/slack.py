"""Slack notification adapter — posts scan results to a configured channel.

The webhook URL is stored Fernet-encrypted on the installation row (set via the
dashboard). Delivery failures are logged and swallowed — notifications never
fail a scan.
"""

import httpx
from sqlalchemy import select

from agents.state import GuardianState
from core.crypto import EncryptionError, decrypt_key
from core.db.models import Installation, Repository, Scan
from core.db.session import get_session_factory
from core.logging import get_logger

log = get_logger("notify.slack")


def build_slack_message(state: GuardianState) -> dict | None:
    prs = state.get("prs", [])
    findings = state.get("findings", [])
    if not findings:
        return None  # clean scans don't ping Slack — noise control

    repo = state["repo_full_name"]
    lines = []
    for f in findings[:5]:
        lines.append(f"• `{f.rule_id}` in `{f.file_path}:{f.start_line}` ({f.severity})")
    pr_lines = [f"• <{p.url}|PR #{p.number}> — {p.branch}" for p in prs]

    text = (
        f"🛡️ *GitGuardian* — `{repo}` @ `{state['commit_sha'][:7]}`\n"
        f"*{len(findings)} finding(s):*\n" + "\n".join(lines)
    )
    if pr_lines:
        text += "\n*Fix PRs awaiting your review:*\n" + "\n".join(pr_lines)
    else:
        text += "\n⚠️ No automatic fix possible — human attention needed."
    text += f"\n_LLM cost: ${state.get('llm_cost_usd', 0):.4f}_"
    return {"text": text}


async def send_slack(state: GuardianState) -> None:
    message = build_slack_message(state)
    if not message:
        return
    try:
        async with get_session_factory()() as s:
            inst = await s.scalar(
                select(Installation)
                .join(Repository, Repository.installation_id == Installation.id)
                .join(Scan, Scan.repository_id == Repository.id)
                .where(Scan.id == state["scan_id"])
            )
        if not inst or not inst.slack_webhook_ciphertext:
            return
        url = decrypt_key(inst.slack_webhook_ciphertext)

        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(url, json=message)
            resp.raise_for_status()
        await log.ainfo("slack notified", repo=state["repo_full_name"])
    except EncryptionError:
        await log.aerror("slack webhook undecryptable")
    except Exception as e:
        await log.awarning("slack delivery failed (swallowed)", error=str(e)[:200])
