"""Router node — validates the push and clones the repo.

Loop prevention is here and non-negotiable: our own fix branches fire push
webhooks too. Skipping them is what stops the agent from scanning itself
into an infinite PR loop.
"""

import asyncio
import base64
import os
import tempfile

from agents.state import GuardianState
from apps.api.github.auth import installation_token
from core.config import get_settings
from core.logging import get_logger

log = get_logger("router")

SCANNABLE_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".yaml",
    ".yml",
    ".env",
    ".toml",
    ".cfg",
    ".ini",
    ".sh",
    ".go",
    ".rb",
    ".java",
}


class SkipScan(Exception):
    """Graceful exit: nothing to do for this push."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def should_skip(ref: str, author_username: str | None) -> str | None:
    """Return a skip reason, or None if the push should be scanned."""
    bot_name = get_settings().github_app_bot_name
    if ref.startswith("refs/heads/gitguardian/"):
        return "our own fix branch"
    if author_username and bot_name in author_username:
        return "commit authored by the app bot"
    if "refs/heads/" not in ref:
        return "not a branch push (tag or other ref)"
    return None


async def _git(*args: str, cwd: str | None = None) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    return proc.returncode, stderr.decode()


async def clone_repo(installation_id: int, repo_full_name: str, commit_sha: str) -> str:
    """Shallow-clone the repo and best-effort checkout the pushed commit.

    Auth uses an Authorization header on the command line invocation only —
    never the remote URL — so the token can't persist in .git/config.
    """
    token = await installation_token(installation_id)
    auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()

    workdir = tempfile.mkdtemp(prefix="gg-work-")
    os.chmod(workdir, 0o755)  # noqa: S103 - worker-local scratch dir

    rc, err = await _git(
        "-c",
        f"http.extraHeader=Authorization: Basic {auth}",
        "clone",
        "--depth",
        "50",
        f"https://github.com/{repo_full_name}.git",
        workdir,
    )
    if rc != 0:
        raise RuntimeError(f"git clone failed: {err[:500]}")

    # Best-effort: shallow clone may not contain the pushed commit; HEAD is fine
    await _git("-C", workdir, "checkout", commit_sha)

    await log.ainfo("repo cloned", workdir=workdir, repo=repo_full_name)
    return workdir


async def router_node(state: GuardianState) -> dict:
    reason = should_skip(state.get("ref", ""), None)
    if reason:
        raise SkipScan(reason)

    workdir = await clone_repo(
        state["installation_id"], state["repo_full_name"], state["commit_sha"]
    )
    return {
        "workdir": workdir,
        "events": [f"router: cloned {state['repo_full_name']}@{state['commit_sha'][:7]}"],
    }
