"""Scanner integration tests — real semgrep/gitleaks containers against vuln_app."""

import shutil
import tempfile
from pathlib import Path

import pytest

from core.schemas import Severity
from security.parsers.gitleaks import parse_gitleaks
from security.parsers.sarif import parse_sarif
from security.runners.gitleaks_runner import GitleaksRunner
from security.runners.semgrep_runner import SemgrepRunner

VULN_APP = Path(__file__).parent.parent / "fixtures" / "vuln_app"

pytestmark = pytest.mark.docker


@pytest.fixture()
def workdir():
    d = tempfile.mkdtemp(prefix="gg-scan-test-")
    Path(d).chmod(0o755)
    shutil.copytree(VULN_APP, Path(d) / "src")
    (Path(d) / "src").chmod(0o755)
    yield str(Path(d) / "src")
    shutil.rmtree(d, ignore_errors=True)


def test_semgrep_finds_dangerous_calls(workdir):
    sarif, err = SemgrepRunner().scan(workdir)
    assert err is None, err
    findings = parse_sarif(sarif, repo_prefix="/work/")
    rule_ids = {f.rule_id for f in findings}
    assert any("shell" in r or "subprocess" in r for r in rule_ids)
    assert all(f.tool == "semgrep" for f in findings)


def test_gitleaks_finds_aws_key(workdir):
    report, err = GitleaksRunner().scan(workdir)
    assert err is None, err
    findings = parse_gitleaks(report)
    assert len(findings) >= 1
    assert all(f.severity == Severity.CRITICAL for f in findings)
    assert any("key" in f.rule_id for f in findings)
    assert all(not f.file_path.startswith("/") for f in findings)
