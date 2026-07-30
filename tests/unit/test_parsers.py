"""Unit tests for SARIF and gitleaks parsers."""

import json
from pathlib import Path

from core.schemas import Severity
from security.parsers.gitleaks import parse_gitleaks
from security.parsers.sarif import parse_sarif

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_sarif_parses_results_with_locations():
    doc = json.loads((FIXTURES / "semgrep_sample.sarif").read_text())
    findings = parse_sarif(doc)
    assert len(findings) == 2  # the location-less result is skipped

    f = findings[0]
    assert f.tool == "semgrep"
    assert f.rule_id == "gitguardian.python-subprocess-shell"
    assert f.file_path == "app/handler.py"  # /src/ prefix stripped
    assert f.start_line == 12
    assert f.severity == Severity.HIGH  # from rule metadata
    assert "shell=True" in f.snippet


def test_sarif_metadata_severity_wins_over_level():
    doc = json.loads((FIXTURES / "semgrep_sample.sarif").read_text())
    f = parse_sarif(doc)[1]
    # metadata "error" maps to HIGH; SARIF level was also "error"
    assert f.severity == Severity.HIGH
    assert f.file_path == "lib/util.py"


def test_sarif_fingerprints_stable_and_distinct():
    doc = json.loads((FIXTURES / "semgrep_sample.sarif").read_text())
    a, b = parse_sarif(doc)
    assert a.fingerprint == a.fingerprint
    assert a.fingerprint != b.fingerprint


def test_gitleaks_redacts_secret_material():
    records = json.loads((FIXTURES / "gitleaks_sample.json").read_text())
    findings = parse_gitleaks(records)
    assert len(findings) == 1

    f = findings[0]
    assert f.tool == "gitleaks"
    assert f.rule_id == "aws-access-token"
    assert f.severity == Severity.CRITICAL
    assert f.file_path == "config/settings.py"
    # secret never survives parsing
    assert f.snippet == ""
    assert "AKIAIOSFODNN7EXAMPLE" not in json.dumps(f.raw)
    assert f.raw["Secret"] == "***REDACTED***"  # noqa: S105


def test_gitleaks_empty_report():
    assert parse_gitleaks("[]") == []
    assert parse_gitleaks([]) == []
