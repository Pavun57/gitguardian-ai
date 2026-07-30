"""Dashboard session auth — GitHub OAuth login, signed JWT session cookie.

Phase 2 scope note: single-tenant. OAuth proves the visitor is a GitHub user;
the dashboard shows all installations (it's your deployment). Multi-tenant
access control (user → installation mapping) is a Phase 4 concern.
"""

import time

import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from core.config import get_settings
from core.logging import get_logger

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("auth")

SESSION_COOKIE = "gg_session"
SESSION_TTL = 7 * 24 * 3600  # 7 days


def create_session(github_login: str, avatar_url: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": github_login, "avatar": avatar_url, "iat": now, "exp": now + SESSION_TTL},
        get_settings().session_secret,
        algorithm="HS256",
    )


def read_session(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    try:
        return jwt.decode(token, get_settings().session_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail="invalid session") from e


@router.get("/github")
async def login():
    s = get_settings()
    return RedirectResponse(
        "https://github.com/login/oauth/authorize"
        f"?client_id={s.github_oauth_client_id}"
        f"&redirect_uri={s.api_base_url}/auth/github/callback"
        "&scope=read:user"
    )


@router.get("/github/callback")
async def callback(code: str, response: Response):
    import httpx

    s = get_settings()
    async with httpx.AsyncClient(timeout=15) as http:
        token_resp = await http.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": s.github_oauth_client_id,
                "client_secret": s.github_oauth_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise HTTPException(status_code=401, detail="OAuth exchange failed")

        user_resp = await http.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user = user_resp.json()

    session = create_session(user["login"], user.get("avatar_url", ""))
    redirect = RedirectResponse(f"{s.dashboard_url}/")
    redirect.set_cookie(
        SESSION_COOKIE,
        session,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
    )
    await log.ainfo("dashboard login", user=user["login"])
    return redirect


@router.get("/me")
async def me(request: Request):
    session = read_session(request)
    return {"login": session["sub"], "avatar": session.get("avatar", "")}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "ok"}
