"""Shared pydantic schemas flowing through the pipeline.

These are the wire/contract types — DB models live in core/db/models.py and LangGraph
state in agents/state.py. Keeping them separate means the scanner parsers, the agents,
and the API can evolve independently.
"""

import hashlib
from enum import StrEnum

from pydantic import BaseModel, Field


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


class ScanStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_FINDINGS = "no_findings"


class FixStatus(StrEnum):
    GENERATED = "generated"
    VALIDATED = "validated"
    TESTS_PASSED = "tests_passed"
    FAILED = "failed"
    NEEDS_HUMAN = "needs_human"


class Finding(BaseModel):
    """A normalized security finding, regardless of which tool produced it."""

    tool: str  # "semgrep" | "gitleaks" | "bandit"
    rule_id: str
    severity: Severity
    file_path: str
    start_line: int
    end_line: int | None = None
    message: str
    snippet: str = ""
    raw: dict = Field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Stable dedup key for 'the same finding' across pushes."""
        material = (
            f"{self.tool}|{self.rule_id}|{self.file_path}|{self.start_line}|{self.snippet[:64]}"
        )
        return hashlib.sha256(material.encode()).hexdigest()


class FixResult(BaseModel):
    """Structured output of the fix agent (forced tool-use schema)."""

    explanation: str
    fixed_file_content: str
    confidence: str  # "high" | "medium" | "low"
    test_file_content: str
    test_file_path: str
    summary_for_pr: str


class TestResult(BaseModel):
    passed: bool
    output: str  # truncated pytest output
    duration_seconds: float
    timed_out: bool = False


class PullRequestRef(BaseModel):
    number: int
    url: str
    branch: str
