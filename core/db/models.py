"""SQLAlchemy models — minimal but extensible data model for Phase 1.

JSONB `raw` columns hold tool-native output where the schema will evolve.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Installation(Base):
    __tablename__ = "installations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # GitHub installation id
    account_login: Mapped[str] = mapped_column(Text)
    slack_webhook_ciphertext: Mapped[bytes | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    uninstalled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    repositories: Mapped[list["Repository"]] = relationship(back_populates="installation")


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # GitHub repo id
    installation_id: Mapped[int] = mapped_column(ForeignKey("installations.id"))
    full_name: Mapped[str] = mapped_column(Text, index=True)
    default_branch: Mapped[str] = mapped_column(Text, default="main")
    is_active: Mapped[bool] = mapped_column(default=True)

    installation: Mapped[Installation] = relationship(back_populates="repositories")


class ApiKey(Base):
    """Agent connections: a user's provider credential, Fernet-encrypted at rest.

    installation_id NULL = global default (used when an installation has no
    specific connection)."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    installation_id: Mapped[int | None] = mapped_column(
        ForeignKey("installations.id"), index=True, nullable=True
    )
    provider: Mapped[str] = mapped_column(Text, default="anthropic")
    ciphertext: Mapped[bytes] = mapped_column()
    key_fingerprint: Mapped[str] = mapped_column(Text)  # "...wxyz" for display
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    commit_sha: Mapped[str] = mapped_column(Text)
    ref: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="queued", index=True)
    trigger: Mapped[str] = mapped_column(Text, default="push")
    llm_cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), default=0)
    langsmith_trace_url: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    fingerprint: Mapped[str] = mapped_column(Text, index=True)  # dedup key
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)

    scan: Mapped[Scan] = relationship(back_populates="findings")
    fix: Mapped["FixRow | None"] = relationship(back_populates="finding")


class FixRow(Base):
    __tablename__ = "fixes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("findings.id"), unique=True)
    status: Mapped[str] = mapped_column(Text, default="generated")
    model: Mapped[str] = mapped_column(Text)
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
    repo_full_name: Mapped[str] = mapped_column(Text)
    number: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text)
    branch: Mapped[str] = mapped_column(Text, index=True)
    state: Mapped[str] = mapped_column(Text, default="open")

    fix: Mapped[FixRow] = relationship(back_populates="pull_request")
