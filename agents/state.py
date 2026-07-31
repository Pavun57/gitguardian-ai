"""LangGraph state schema — local-first: one invocation handles one commit."""

from typing import Annotated, TypedDict

from core.schemas import Finding, FixResult, PullRequestRef, TestResult


def _append(a: list, b: list) -> list:
    return a + b


class GuardianState(TypedDict, total=False):
    scan_id: str  # UUID; also the LangGraph thread_id
    repo_path: str  # local repo root
    workdir: str  # directory the scanner/fix/test nodes operate on (== repo_path locally)
    branch: str  # current branch
    commit_message: str  # user's -m message
    scan_scope: str  # 'staged' (commit) | 'all_changes' (scan) | 'full'

    findings: list[Finding]
    findings_index: int
    current_finding: Finding | None

    fix_attempts: int
    last_test_output: str | None
    fix: FixResult | None
    test_result: TestResult | None
    fixed_files: Annotated[list[str], _append]  # files changed by applied fixes
    prs: Annotated[list[PullRequestRef], _append]

    error: str | None
    llm_cost_usd: float
    llm_input_tokens: int
    llm_output_tokens: int
    trace_url: str | None

    events: Annotated[list[str], _append]
