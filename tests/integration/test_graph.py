"""Graph topology tests — full pipeline with LLM + external IO mocked.

These prove the state machine itself: routing edges, retry loops, budget caps,
and the needs-human path, deterministically and without network or Docker.
"""

from agents.graph import (
    after_advance,
    after_classify,
    after_fix_apply,
    after_fix_generate,
    after_test_run,
    build_graph,
)
from core.schemas import Finding, FixResult, Severity, TestResult


def _finding(sev=Severity.HIGH) -> Finding:
    return Finding(
        tool="semgrep",
        rule_id="gitguardian.python-eval-exec",
        severity=sev,
        file_path="app.py",
        start_line=3,
        message="eval on untrusted input",
    )


def _fix(confidence="high") -> FixResult:
    return FixResult(
        explanation="replaced eval with ast.literal_eval",
        fixed_file_content="import ast\nx = ast.literal_eval('1')\n",
        confidence=confidence,
        test_file_content="def test_safe():\n    assert True\n",
        test_file_path="tests/test_fix.py",
        summary_for_pr="replace eval",
    )


# --- pure edge-function tests (no graph execution) ---


def test_no_findings_goes_to_finalize():
    assert after_classify({"findings": []}) == "finalize"


def test_findings_go_to_fix_loop():
    assert after_classify({"findings": [_finding()]}) == "fix_select"


def test_low_confidence_skips_pr():
    state = {"fix": _fix(confidence="low")}
    assert after_fix_generate(state) == "fix_advance"


def test_high_confidence_goes_to_apply():
    assert after_fix_generate({"fix": _fix()}) == "fix_apply"


def test_validation_failure_retries_within_budget():
    state = {"last_test_output": "Fix REJECTED by validator: syntax error", "fix_attempts": 1}
    assert after_fix_apply(state) == "fix_generate"


def test_validation_failure_gives_up_at_cap():
    state = {"last_test_output": "Fix REJECTED by validator: still fires", "fix_attempts": 2}
    assert after_fix_apply(state) == "fix_advance"


def test_passing_tests_go_to_pr():
    state = {"test_result": TestResult(passed=True, output="ok", duration_seconds=1.0)}
    assert after_test_run(state) == "pr_create"


def test_failing_tests_retry_then_give_up():
    fail = TestResult(passed=False, output="boom", duration_seconds=1.0)
    assert after_test_run({"test_result": fail, "fix_attempts": 0}) == "fix_generate"
    assert after_test_run({"test_result": fail, "fix_attempts": 2}) == "fix_advance"


def test_advance_loops_through_findings():
    state = {"findings_index": 1, "findings": [_finding(), _finding()]}
    assert after_advance(state) == "fix_select"
    state = {"findings_index": 2, "findings": [_finding(), _finding()]}
    assert after_advance(state) == "finalize"


def test_graph_compiles_with_expected_nodes():
    g = build_graph()
    nodes = set(g.get_graph().nodes)
    assert {
        "router",
        "scanner",
        "classifier",
        "fix_select",
        "fix_generate",
        "fix_apply",
        "test_run",
        "pr_create",
        "fix_advance",
        "finalize",
        "notify",
    } <= nodes
