"""Central configuration via pydantic-settings. All env vars documented in .env.example."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives at the install root (two levels up from core/config.py), so the
# CLI finds it even when invoked from the user's repo via `gitguardian commit`.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # GitHub App
    github_app_id: str = ""
    github_app_slug: str = ""  # e.g. "gitguardian-ai" — from the app's settings page URL
    github_app_private_key_path: Path = Path("./secrets/github-app.pem")
    github_webhook_secret: str = ""
    github_app_bot_name: str = "gitguardian-ai"
    github_api_base: str = "https://api.github.com"

    # Anthropic (env fallback until BYOK dashboard exists)
    anthropic_api_key: str = ""

    # Infrastructure
    database_url: str = "postgresql+asyncpg://gitguardian:gitguardian@localhost:5432/gitguardian"
    redis_url: str = "redis://localhost:6379/0"

    # BYOK encryption
    master_encryption_key: str = ""

    # LangSmith
    langsmith_api_key: str = ""
    langsmith_project: str = "gitguardian-ai"
    langsmith_tracing: bool = False

    # Pipeline tuning
    max_findings_per_scan: int = 3
    max_fix_attempts: int = 2
    scan_budget_usd: float = 0.50
    fix_model: str = "claude-sonnet-4-5"
    classify_model: str = "claude-haiku-4-5"
    max_file_lines: int = 1500

    # Scanners / test isolation
    semgrep_image: str = "semgrep/semgrep:1.131.0"
    gitleaks_image: str = "zricethezav/gitleaks:v8.28.0"
    test_runner_image: str = "gitguardian/test-runner:latest"
    scan_timeout_seconds: int = 300
    test_timeout_seconds: int = 120

    # Dev tunnel
    smee_channel_url: str = ""

    # Dashboard (Phase 2)
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    session_secret: str = ""
    dashboard_url: str = "http://localhost:5678"
    api_base_url: str = "http://localhost:8976"


@lru_cache
def get_settings() -> Settings:
    return Settings()
