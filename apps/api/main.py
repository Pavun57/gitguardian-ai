"""FastAPI app factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers import agents, auth, dashboard, health, tunnel, webhooks
from core.config import get_settings
from core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    yield


app = FastAPI(title="GitGuardian AI", version="0.1.0", lifespan=lifespan)

# Dashboard runs on a different origin in dev (Next.js :3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().dashboard_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(webhooks.router)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(agents.router)
app.include_router(tunnel.router)
