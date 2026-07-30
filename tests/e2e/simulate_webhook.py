"""Local webhook simulator — posts a signed push/installation payload to the API.

Useful for dev without smee:
  uv run python tests/e2e/simulate_webhook.py installation
  uv run python tests/e2e/simulate_webhook.py push <repo_id> <full_name> <sha>
"""

import hashlib
import hmac
import json
import sys
import uuid

import httpx

from core.config import get_settings

API = "http://localhost:8000/webhooks/github"


def _post(event: str, payload: dict) -> None:
    body = json.dumps(payload).encode()
    secret = get_settings().github_webhook_secret
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    resp = httpx.post(
        API,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": str(uuid.uuid4()),
        },
        timeout=10,
    )
    print(resp.status_code, resp.text)


def installation(repo_id: int = 9001, full_name: str = "you/demo-repo") -> None:
    _post(
        "installation",
        {
            "action": "created",
            "installation": {"id": 5001, "account": {"login": "you"}},
            "repositories": [{"id": repo_id, "full_name": full_name, "default_branch": "main"}],
        },
    )


def push(repo_id: int, full_name: str, sha: str) -> None:
    _post(
        "push",
        {
            "ref": "refs/heads/main",
            "after": sha,
            "repository": {"id": repo_id, "full_name": full_name, "default_branch": "main"},
            "head_commit": {"id": sha, "author": {"username": "you"}},
            "installation": {"id": 5001},
        },
    )


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] == "installation":
        installation(*[int(sys.argv[2]) if len(sys.argv) > 2 else 9001])
    elif sys.argv[1] == "push":
        push(int(sys.argv[2]), sys.argv[3], sys.argv[4])
    else:
        print(__doc__)
