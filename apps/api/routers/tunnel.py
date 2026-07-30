"""Webhook tunnel management — smee channel enterable from the UI.

The API manages a `gitguardian-smee` Docker container on the host, so users
never touch the command line for the tunnel. The channel URL is stored
encrypted in app_config.
"""

import docker
from docker.errors import NotFound
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from apps.api.routers.auth import read_session
from core.appconfig import get_config, set_config
from core.logging import get_logger

router = APIRouter(prefix="/api/tunnel", tags=["tunnel"])
log = get_logger("tunnel")

CONTAINER_NAME = "gitguardian-smee"


def _session(request: Request) -> dict:
    return read_session(request)


def _container():
    try:
        return docker.from_env().containers.get(CONTAINER_NAME)
    except NotFound:
        return None


def _start_container(channel_url: str) -> None:
    client = docker.from_env()
    try:
        client.containers.get(CONTAINER_NAME).remove(force=True)
    except NotFound:
        pass
    client.containers.run(
        "node:22-alpine",
        command=(
            f"sh -c 'npm install -g smee-client 2>/dev/null && "
            f"smee --url {channel_url} --target http://localhost:8000/webhooks/github'"
        ),
        name=CONTAINER_NAME,
        network_mode="host",
        restart_policy={"Name": "unless-stopped"},
        detach=True,
    )


class TunnelIn(BaseModel):
    channel_url: str


@router.get("")
async def tunnel_status(_=Depends(_session)):
    c = _container()
    return {
        "channel_url": await get_config("smee_channel_url"),
        "running": c is not None and c.status == "running",
    }


@router.post("")
async def tunnel_start(body: TunnelIn, _=Depends(_session)):
    url = body.channel_url.strip()
    if not url.startswith("https://smee.io/"):
        raise HTTPException(400, "must be a https://smee.io/ channel URL")
    await set_config("smee_channel_url", url)
    try:
        _start_container(url)
    except Exception as e:
        raise HTTPException(500, f"failed to start tunnel: {str(e)[:300]}") from e
    await log.ainfo("tunnel started")
    return {"status": "running"}


@router.delete("")
async def tunnel_stop(_=Depends(_session)):
    c = _container()
    if c:
        c.remove(force=True)
    return {"status": "stopped"}
