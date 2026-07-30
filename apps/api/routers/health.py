"""Health endpoints for compose healthchecks and future load balancers."""

from fastapi import APIRouter
from sqlalchemy import text

from core.db.session import get_engine

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> dict:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ready"}
