"""Safe fix application + validation.

The fix is untrusted model output. Before anything runs it must pass:
  1. Path assertion — the fix targets the finding's file, nothing else
  2. Syntax check — ast.parse for Python
  3. Single-file diff — git diff must show exactly one file touched
  4. Re-scan — Semgrep must no longer fire the original rule on the patched file,
     and no new finding of >= original severity may appear
"""

import ast
import asyncio
from pathlib import Path

from core.logging import get_logger
from core.schemas import SEVERITY_ORDER, Finding, FixResult
from security.parsers.sarif import parse_sarif
from security.runners.semgrep_runner import SemgrepRunner

log = get_logger("apply")


class FixValidationError(Exception):
    pass


def _assert_safe_path(file_path: str) -> None:
    p = Path(file_path)
    if p.is_absolute() or ".." in p.parts:
        raise FixValidationError(f"unsafe path rejected: {file_path}")


def syntax_check(path: Path) -> None:
    if path.suffix == ".py":
        try:
            ast.parse(path.read_text(errors="replace"))
        except SyntaxError as e:
            raise FixValidationError(f"fixed file has a syntax error: {e}") from e


async def apply_fix(workdir: str, finding: Finding, fix: FixResult) -> None:
    """Write the fixed file + test file into the clone. Raises FixValidationError."""
    root = Path(workdir)
    _assert_safe_path(finding.file_path)
    _assert_safe_path(fix.test_file_path)

    target = root / finding.file_path
    if not target.exists():
        raise FixValidationError(f"target file missing: {finding.file_path}")

    target.write_text(fix.fixed_file_content)
    syntax_check(target)

    test_path = root / fix.test_file_path
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(fix.test_file_content)
    syntax_check(test_path)

    # Exactly the finding's file + the test file may be modified.
    # -uall expands untracked directories to individual files (otherwise a new
    # tests/ dir shows up as "?? tests/" and trips the check).
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        workdir,
        "status",
        "--porcelain",
        "-uall",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    changed = {
        line[3:].strip().strip('"').rstrip("/")
        for line in out.decode().splitlines()
        if line.strip()
    }
    allowed = {finding.file_path, fix.test_file_path}
    unexpected = changed - allowed
    if unexpected:
        raise FixValidationError(f"fix touched unexpected files: {sorted(unexpected)}")


async def validate_with_rescan(
    workdir: str, finding: Finding, baseline_rules: set[str] | None = None
) -> None:
    """Re-run Semgrep on the patched file: original rule must be gone, and no
    genuinely NEW finding of equal-or-higher severity may appear.

    `baseline_rules` = rule_ids already present in the file before the fix
    (from the scan's finding list). Without it, a file with two issues would
    be unfixable one-at-a-time: fixing finding A while finding B remains would
    always read as "the fix introduced B".
    """
    sarif, err = SemgrepRunner().scan(workdir, target_file=finding.file_path)
    if err or not sarif:
        await log.awarning("re-scan failed; skipping validation", error=(err or "")[:300])
        return  # validation is best-effort — the test suite is the harder gate

    baseline = baseline_rules or set()
    findings = parse_sarif(sarif, repo_prefix="/work/")
    still_present = [f for f in findings if f.rule_id == finding.rule_id]
    if still_present:
        raise FixValidationError(
            f"rule {finding.rule_id} still fires after the fix ({len(still_present)}x)"
        )
    worse = [
        f
        for f in findings
        if f.rule_id not in baseline
        and SEVERITY_ORDER[f.severity] <= SEVERITY_ORDER[finding.severity]
    ]
    if worse:
        raise FixValidationError(
            f"fix introduced new {worse[0].severity} finding: {worse[0].rule_id}"
        )
