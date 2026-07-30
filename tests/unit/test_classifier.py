"""Unit tests for classifier fixture-path filtering."""

from agents.classifier.node import drop_fixture_findings, sort_by_severity
from core.schemas import Finding, Severity


def _f(path: str, sev=Severity.HIGH) -> Finding:
    return Finding(
        tool="semgrep",
        rule_id="r",
        severity=sev,
        file_path=path,
        start_line=1,
        message="m",
    )


def test_fixture_paths_dropped():
    findings = [
        _f("tests/fixtures/vuln_app/vulnerable.py"),
        _f("evals/datasets/vulnerable/sqli.py"),
        _f("examples/demo.py"),
        _f("src/handler.py"),
        _f("test_vuln.py"),
    ]
    kept, dropped = drop_fixture_findings(findings)
    assert {f.file_path for f in kept} == {"src/handler.py", "test_vuln.py"}
    assert len(dropped) == 3


def test_root_level_test_file_kept():
    # test_vuln.py at the repo root is NOT a fixture — it must survive
    kept, dropped = drop_fixture_findings([_f("test_vuln.py")])
    assert len(kept) == 1
    assert not dropped


def test_severity_sort():
    findings = [_f("a", Severity.LOW), _f("b", Severity.CRITICAL), _f("c", Severity.MEDIUM)]
    ordered = sort_by_severity(findings)
    assert [f.severity for f in ordered] == [Severity.CRITICAL, Severity.MEDIUM, Severity.LOW]
