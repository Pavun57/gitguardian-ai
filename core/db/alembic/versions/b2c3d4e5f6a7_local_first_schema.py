"""local-first schema: drop GitHub App tables, rebuild scans

Revision ID: b2c3d4e5f6a7
Revises: c8930f517df0
Create Date: 2026-07-30

The product pivoted from GitHub-App/webhook mode to local-first
(`gitguardian commit`). installations/repositories/api_keys are gone;
scans now reference a local repo_path.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "c8930f517df0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop everything from the GitHub-App era (DB was already cleared)
    for table in [
        "pull_requests",
        "fixes",
        "findings",
        "scans",
        "api_keys",
        "repositories",
        "installations",
    ]:
        op.drop_table(table)

    op.create_table(
        "scans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("repo_path", sa.Text(), nullable=False),
        sa.Column("branch", sa.Text(), server_default=""),
        sa.Column("trigger", sa.Text(), server_default="commit"),
        sa.Column("status", sa.Text(), server_default="queued"),
        sa.Column("llm_cost_usd", sa.Numeric(10, 6), server_default="0"),
        sa.Column("trace_url", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_scans_repo_path", "scans", ["repo_path"])
    op.create_index("ix_scans_status", "scans", ["status"])

    op.create_table(
        "findings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("raw", postgresql.JSONB(), server_default="{}"),
    )
    op.create_index("ix_findings_scan_id", "findings", ["scan_id"])
    op.create_index("ix_findings_severity", "findings", ["severity"])
    op.create_index("ix_findings_fingerprint", "findings", ["fingerprint"])

    op.create_table(
        "fixes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("finding_id", sa.Uuid(), unique=True, nullable=False),
        sa.Column("status", sa.Text(), server_default="generated"),
        sa.Column("model", sa.Text(), server_default=""),
        sa.Column("attempts", sa.Integer(), server_default="0"),
        sa.Column("original_content", sa.Text(), nullable=True),
        sa.Column("fixed_content", sa.Text(), nullable=True),
        sa.Column("test_content", sa.Text(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), server_default="0"),
        sa.Column("tokens_out", sa.Integer(), server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 6), server_default="0"),
    )

    op.create_table(
        "pull_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("fix_id", sa.Uuid(), unique=True, nullable=False),
        sa.Column("repo_path", sa.Text(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("url", sa.Text(), server_default=""),
        sa.Column("branch", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), server_default="open"),
    )
    op.create_index("ix_pull_requests_branch", "pull_requests", ["branch"])

    op.create_table(
        "agent_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_fingerprint", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    for table in ["agent_connections", "pull_requests", "fixes", "findings", "scans"]:
        op.drop_table(table)
