"""GitHub App authentication: App JWT (RS256) + installation access tokens.

Credentials resolve via core/appconfig (DB → env fallback), so the app can be
configured from the dashboard without touching .env.

JWT is minted in-process (9-minute expiry, cached). Installation tokens (1h TTL)
are cached in Redis so the api and worker processes share them.
"""

import time

import jwt
import redis.asyncio as aioredis

from core.appconfig import get_config
from core.config import get_settings
from core.logging import get_logger

log = get_logger("github.auth")

_jwt_cache: tuple[str, float] | None = None  # (token, expires_at_epoch)
_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(get_settings().redis_url)
    return _redis


async def app_jwt() -> str:
    """RS256 JWT authenticating as the GitHub App itself."""
    global _jwt_cache
    now = time.time()
    if _jwt_cache and _jwt_cache[1] > now + 30:
        return _jwt_cache[0]

    app_id = await get_config("github_app_id")
    private_key = await get_config("github_app_private_key")
    if not app_id or not private_key:
        raise RuntimeError(
            "GitHub App credentials not configured — add them in the dashboard "
            "(Settings → GitHub App) or .env"
        )

    token = jwt.encode(
        {
            "iat": int(now) - 60,
            "exp": int(now) + 540,  # 9 min, GitHub max is 10
            "iss": app_id,
        },
        private_key,
        algorithm="RS256",
    )
    _jwt_cache = (token, now + 540)
    return token


async def installation_token(installation_id: int, http_client=None) -> str:
    """Installation access token, Redis-cached with T-5min refresh."""
    cache_key = f"gh:token:{installation_id}"
    cached = await _get_redis().get(cache_key)
    if cached:
        return cached.decode()

    if http_client is None:
        import httpx

        http_client = httpx.AsyncClient(timeout=30)

    resp = await http_client.post(
        f"{get_settings().github_api_base}/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {await app_jwt()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["token"]
    # Tokens live 1h; cache for 55 min
    await _get_redis().set(cache_key, token, ex=3300)
    await log.ainfo("minted installation token", installation_id=installation_id)
    return token
