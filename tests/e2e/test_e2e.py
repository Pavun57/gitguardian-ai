"""E2E: full pipeline against a live GitHub repo.

Prerequisites (manual, one-time):
  1. GitHub App created with permissions per README, installed on a test repo
  2. .env populated (APP_ID, private key, webhook secret, ANTHROPIC_API_KEY)
  3. `docker compose --profile tunnel up` running (api + worker + smee)
  4. A deliberately vulnerable test repo (tests/fixtures/vuln_app pushed to it)

Run: uv run pytest -m e2e -s
Marked e2e — excluded from CI and from the default suite.
"""

import os

import pytest

pytestmark = pytest.mark.e2e


@pytest.mark.skipif(
    not os.environ.get("GG_E2E_REPO"), reason="set GG_E2E_REPO=owner/repo to run live e2e"
)
async def test_push_triggers_fix_pr():
    """The real proof: push a vuln, watch a fix PR appear.

    This test drives git + the GitHub API directly against GG_E2E_REPO and
    asserts that within N minutes a gitguardian/fix-* PR is opened.
    """
    import asyncio
    import subprocess
    import tempfile
    from pathlib import Path

    import httpx

    repo = os.environ["GG_E2E_REPO"]
    token = os.environ["GG_E2E_PAT"]  # personal access token for pushing test vulns
    assert token, "GG_E2E_PAT required"

    workdir = tempfile.mkdtemp()
    subprocess.run(
        ["git", "clone", f"https://x-access-token:{token}@github.com/{repo}.git", workdir],
        check=True,
        capture_output=True,
    )

    vuln = Path(__file__).parent.parent / "fixtures" / "vuln_app" / "vulnerable.py"
    target = Path(workdir) / f"vuln_{os.urandom(3).hex()}.py"
    target.write_text(vuln.read_text())

    subprocess.run(["git", "add", "."], cwd=workdir, check=True)
    subprocess.run(
        ["git", "-c", "user.email=e2e@test", "-c", "user.name=e2e", "commit", "-m", "add vuln"],
        cwd=workdir,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "push"], cwd=workdir, check=True, capture_output=True)

    # Poll for the fix PR (pipeline takes a few minutes end-to-end)
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    ) as http:
        for _ in range(60):  # up to 10 minutes
            resp = await http.get(
                f"https://api.github.com/repos/{repo}/pulls", params={"state": "open"}
            )
            prs = [p for p in resp.json() if p["head"]["ref"].startswith("gitguardian/fix-")]
            if prs:
                print(f"\n✅ E2E PASSED — fix PR opened: {prs[0]['html_url']}")
                return
            await asyncio.sleep(10)

    pytest.fail("no gitguardian/fix-* PR appeared within 10 minutes")
