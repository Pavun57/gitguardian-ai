"""LangGraph state schema — one graph invocation handles one push."""

from typing import Annotated, TypedDict

from core.schemas import Finding, FixResult, PullRequestRef, TestResult


def _append(a: list, b: list) -> list:
    return a + b


class GuardianState(TypedDict, total=False):
    scan_id: str  # UUID; also the LangGraph thread_id
    installation_id: int
    repo_full_name: str
    commit_sha: str
    ref: str
    workdir: str  # temp clone path on the worker

    findings: list[Finding]  # normalized, post-classify, severity-sorted
    findings_index: int  # which finding the fix loop is on
    current_finding: Finding | None

    fix_attempts: int
    last_test_output: str | None  # fed back into the fix prompt on retry
    fix: FixResult | None
    test_result: TestResult | None
    prs: Annotated[list[PullRequestRef], _append]

    check_run_id: int | None
    error: str | None
    llm_cost_usd: float
    llm_input_tokens: int
    llm_output_tokens: int

    # audit trail of node transitions (appended, never overwritten)
    events: Annotated[list[str], _append]
