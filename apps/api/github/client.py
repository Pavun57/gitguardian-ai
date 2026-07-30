"""Thin async GitHub REST client with retry/backoff on transient errors."""

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from apps.api.github.auth import installation_token
from core.config import get_settings
from core.logging import get_logger

log = get_logger("github.client")


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout))


class GitHubClient:
    def __init__(self, installation_id: int):
        self.installation_id = installation_id
        self.base = get_settings().github_api_base
        self._http = httpx.AsyncClient(timeout=30)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def _headers(self) -> dict:
        token = await installation_token(self.installation_id, self._http)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @retry(
        retry=retry_if_exception(_is_transient),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        resp = await self._http.request(
            method, f"{self.base}{path}", headers=await self._headers(), **kwargs
        )
        resp.raise_for_status()
        return resp

    async def get(self, path: str, **kwargs) -> dict:
        return (await self._request("GET", path, **kwargs)).json()

    async def post(self, path: str, **kwargs) -> dict:
        return (await self._request("POST", path, **kwargs)).json()

    async def patch(self, path: str, **kwargs) -> dict:
        return (await self._request("PATCH", path, **kwargs)).json()

    # --- domain helpers ---

    async def get_default_branch(self, repo: str) -> str:
        data = await self.get(f"/repos/{repo}")
        return data["default_branch"]

    async def create_branch(self, repo: str, branch: str, from_sha: str) -> None:
        try:
            await self.post(
                f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": from_sha}
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 422:  # branch already exists — fine (dedup)
                return
            raise

    async def get_branch_sha(self, repo: str, branch: str) -> str:
        data = await self.get(f"/repos/{repo}/branches/{branch}")
        return data["commit"]["sha"]

    async def create_or_update_file(
        self,
        repo: str,
        path: str,
        content_b64: str,
        message: str,
        branch: str,
        sha: str | None = None,
    ) -> dict:
        payload = {"message": message, "content": content_b64, "branch": branch}
        if sha:
            payload["sha"] = sha
        return await self._request("PUT", f"/repos/{repo}/contents/{path}", json=payload).json()

    async def find_open_pr(self, repo: str, branch: str) -> dict | None:
        prs = await self.get(
            f"/repos/{repo}/pulls",
            params={"head": f"{repo.split('/')[0]}:{branch}", "state": "open"},
        )
        return prs[0] if prs else None

    async def create_pr(self, repo: str, title: str, body: str, head: str, base: str) -> dict:
        return await self.post(
            f"/repos/{repo}/pulls",
            json={
                "title": title,
                "body": body,
                "head": head,
                "base": base,
                "maintainer_can_modify": True,
            },
        )

    async def comment_on_pr(self, repo: str, number: int, body: str) -> None:
        await self.post(f"/repos/{repo}/issues/{number}/comments", json={"body": body})
