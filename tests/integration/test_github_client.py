"""GitHub client integration tests — REST mocked with respx."""

import pytest
import respx
from httpx import Response

from apps.api.github.client import GitHubClient

BASE = "https://api.github.com"


@pytest.fixture(autouse=True)
def _mock_token(monkeypatch):
    async def fake_token(installation_id, http_client=None):
        return "test-installation-token"

    monkeypatch.setattr("apps.api.github.client.installation_token", fake_token)


@respx.mock
async def test_create_pr():
    respx.post(f"{BASE}/repos/o/r/pulls").mock(
        return_value=Response(201, json={"number": 7, "html_url": "https://github.com/o/r/pull/7"})
    )
    async with GitHubClient(123) as client:
        pr = await client.create_pr("o/r", "t", "b", "head", "main")
    assert pr["number"] == 7


@respx.mock
async def test_create_branch_idempotent_on_422():
    respx.post(f"{BASE}/repos/o/r/git/refs").mock(
        return_value=Response(422, json={"message": "Reference already exists"})
    )
    async with GitHubClient(123) as client:
        await client.create_branch("o/r", "gitguardian/fix-x-abc1234", "deadbeef")


@respx.mock
async def test_find_open_pr():
    respx.get(f"{BASE}/repos/o/r/pulls").mock(
        return_value=Response(200, json=[{"number": 3, "html_url": "u"}])
    )
    async with GitHubClient(123) as client:
        pr = await client.find_open_pr("o/r", "gitguardian/fix-x")
    assert pr["number"] == 3


@respx.mock
async def test_find_open_pr_none():
    respx.get(f"{BASE}/repos/o/r/pulls").mock(return_value=Response(200, json=[]))
    async with GitHubClient(123) as client:
        assert await client.find_open_pr("o/r", "branch") is None


@respx.mock
async def test_check_run_update():
    from apps.api.github.checks import update_check
    from core.schemas import Finding, Severity

    route = respx.patch(f"{BASE}/repos/o/r/check-runs/42").mock(return_value=Response(200, json={}))
    async with GitHubClient(123) as client:
        await update_check(
            client,
            "o/r",
            42,
            status="completed",
            conclusion="neutral",
            title="t",
            summary="s",
            findings=[
                Finding(
                    tool="semgrep",
                    rule_id="r",
                    severity=Severity.HIGH,
                    file_path="a.py",
                    start_line=5,
                    message="m",
                )
            ],
        )
    assert route.called
    payload = route.calls[0].request.read()
    assert b"annotations" in payload
    assert b"a.py" in payload
