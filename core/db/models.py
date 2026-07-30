"""SQLAlchemy models — local-first data model.

Local repos are identified by path (no GitHub App installations). Agent
connections and app config are global (single-user machine).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AppConfig(Base):
    """Runtime configuration entered via the UI (agent creds, langfuse keys,
    slack webhook). Values Fernet-encrypted."""

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentConnection(Base):
    """Which coding agent to use for fixes: 'claude_code' | 'codex' | 'anthropic'.
    credential may be the CLI_MANAGED marker (the CLI authenticates itself)."""

    __tablename__ = "agent_connections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(Text)
    ciphertext: Mapped[bytes] = mapped_column()
    key_fingerprint: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repo_path: Mapped[str] = mapped_column(Text, index=True)  # local repo root
    branch: Mapped[str] = mapped_column(Text, default="")
    trigger: Mapped[str] = mapped_column(Text, default="commit")  # 'commit' | 'manual'
    status: Mapped[str] = mapped_column(Text, default="queued", index=True)
    llm_cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), default=0)
    trace_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # Langfuse trace
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    findings: Mapped[list["FindingRow"]] = relationship(back_populates="scan")


class FindingRow(Base):
    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scans.id"), index=True)
    tool: Mapped[str] = mapped_column(Text)
    rule_id: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text, index=True)
    file_path: Mapped[str] = mapped_column(Text)
    start_line: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(Text, index=True)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)

    scan: Mapped[Scan] = relationship(back_populates="findings")
    fix: Mapped["FixRow | None"] = relationship(back_populates="finding")


class FixRow(Base):
    __tablename__ = "fixes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("findings.id"), unique=True)
    status: Mapped[str] = mapped_column(Text, default="generated")
    model: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    original_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    fixed_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), default=0)

    finding: Mapped[FindingRow] = relationship(back_populates="fix")
    pull_request: Mapped["PullRequestRow | None"] = relationship(back_populates="fix")


class PullRequestRow(Base):
    __tablename__ = "pull_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    fix_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fixes.id"), unique=True)
    repo_path: Mapped[str] = mapped_column(Text)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str] = mapped_column(Text, default="")
    branch: Mapped[str] = mapped_column(Text, index=True)
    state: Mapped[str] = mapped_column(Text, default="open")

    fix: Mapped[FixRow] = relationship(back_populates="pull_request")
