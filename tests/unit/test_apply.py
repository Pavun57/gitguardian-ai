"""Unit tests for safe fix application (agents/fix_generator/apply.py)."""

import subprocess
from pathlib import Path

import pytest

from agents.fix_generator.apply import FixValidationError, apply_fix, syntax_check
from core.schemas import Finding, FixResult, Severity


@pytest.fixture()
def workdir(tmp_path):
    """A real git repo with one vulnerable file."""
    (tmp_path / "app.py").write_text("def f(x):\n    return eval(x)\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=tmp_path,
        check=True,
    )
    return str(tmp_path)


def _finding(path="app.py") -> Finding:
    return Finding(
        tool="semgrep",
        rule_id="gitguardian.python-eval-exec",
        severity=Severity.HIGH,
        file_path=path,
        start_line=2,
        message="eval",
    )


def _fix(test_path="tests/test_fix.py") -> FixResult:
    return FixResult(
        explanation="use literal_eval",
        fixed_file_content="import ast\n\ndef f(x):\n    return ast.literal_eval(x)\n",
        confidence="high",
        test_file_content="def test_ok():\n    assert True\n",
        test_file_path=test_path,
        summary_for_pr="fix",
    )


async def test_apply_writes_files(workdir):
    await apply_fix(workdir, _finding(), _fix())
    assert "literal_eval" in (Path(workdir) / "app.py").read_text()
    assert (Path(workdir) / "tests/test_fix.py").exists()


async def test_syntax_error_rejected(workdir):
    bad = _fix()
    bad.fixed_file_content = "def broken(:\n"
    with pytest.raises(FixValidationError, match="syntax error"):
        await apply_fix(workdir, _finding(), bad)


async def test_path_traversal_rejected(workdir):
    with pytest.raises(FixValidationError, match="unsafe path"):
        await apply_fix(workdir, _finding(path="../evil.py"), _fix())


async def test_absolute_test_path_rejected(workdir):
    with pytest.raises(FixValidationError, match="unsafe path"):
        await apply_fix(workdir, _finding(), _fix(test_path="/etc/cron.d/x.py"))


async def test_missing_target_rejected(workdir):
    with pytest.raises(FixValidationError, match="missing"):
        await apply_fix(workdir, _finding(path="ghost.py"), _fix())


def test_syntax_check_passes_valid_python(tmp_path):
    f = tmp_path / "ok.py"
    f.write_text("x = 1\n")
    syntax_check(f)
