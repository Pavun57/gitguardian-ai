"""Scanner node — runs Semgrep + Gitleaks over the repo, normalizes findings.

Scope: by default only files changed in the commit (staged) or working tree
are scanned — a pre-commit check should vet what you're committing, not
re-litigate the entire repo on every commit.
"""

import asyncio
import uuid

from agents.state import GuardianState
from core.db.models import FindingRow
from core.db.session import get_session_factory
from core.logging import get_logger
from core.schemas import Finding
from security.parsers.gitleaks import parse_gitleaks
from security.parsers.sarif import parse_sarif
from security.runners.gitleaks_runner import GitleaksRunner
from security.runners.semgrep_runner import SemgrepRunner

log = get_logger("scanner")

# Above this many changed files a targeted scan stops paying off — scan everything
MAX_TARGET_FILES = 200


async def _git(*args: str, cwd: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode().strip()


async def changed_files(workdir: str, staged: bool) -> list[str]:
    """Files this scan should vet: staged (commit flow) or all changes vs HEAD."""
    if staged:
        rc, out = await _git(
            "diff", "--cached", "--name-only", "--diff-filter=ACMR", cwd=workdir
        )
        return out.splitlines() if rc == 0 and out else []
    rc, out = await _git("diff", "HEAD", "--name-only", "--diff-filter=ACMR", cwd=workdir)
    files = out.splitlines() if rc == 0 and out else []
    rc, out = await _git("ls-files", "--others", "--exclude-standard", cwd=workdir)
    if rc == 0 and out:
        files += out.splitlines()
    return files


async def run_scanners(workdir: str, only_files: list[str] | None = None) -> list[Finding]:
    """Both scanners in parallel; one failing doesn't sink the other.

    only_files: semgrep scans just these; gitleaks has no per-file mode in
    filesystem scans, so its report is post-filtered to the same set.
    """
    semgrep = SemgrepRunner()
    gitleaks = GitleaksRunner()

    sarif_result, gitleaks_result = await asyncio.gather(
        asyncio.to_thread(semgrep.scan, workdir, only_files),
        asyncio.to_thread(gitleaks.scan, workdir),
        return_exceptions=True,
    )

    findings: list[Finding] = []

    if isinstance(sarif_result, Exception):
        await log.aerror("semgrep crashed", error=str(sarif_result)[:500])
    else:
        sarif, err = sarif_result
        if err:
            await log.aerror("semgrep failed", error=err[:500])
        elif sarif:
            findings.extend(parse_sarif(sarif, repo_prefix="/work/"))

    if isinstance(gitleaks_result, Exception):
        await log.aerror("gitleaks crashed", error=str(gitleaks_result)[:500])
    else:
        report, err = gitleaks_result
        if err:
            await log.aerror("gitleaks failed", error=err[:500])
        elif report:
            gl = parse_gitleaks(report)
            if only_files is not None:
                wanted = set(only_files)
                gl = [f for f in gl if f.file_path in wanted]
            findings.extend(gl)

    return findings


async def scanner_node(state: GuardianState) -> dict:
    workdir = state["workdir"]
    scope = state.get("scan_scope", "all_changes")
    events: list[str] = []

    only: list[str] | None = None
    if scope != "full":
        changed = await changed_files(workdir, staged=(scope == "staged"))
        if not changed and scope == "staged":
            # nothing staged → nothing to vet (commit cmd guards this already)
            only = []
            events.append("scanner: no staged changes — nothing to scan")
        elif changed and len(changed) <= MAX_TARGET_FILES:
            only = changed
            events.append(f"scanner: scoped to {len(changed)} changed file(s)")
        elif changed:
            events.append(
                f"scanner: {len(changed)} changed files > {MAX_TARGET_FILES} — full scan"
            )
        else:
            events.append("scanner: working tree clean — full scan")

    findings = [] if only == [] else await run_scanners(workdir, only)

    # Persist raw findings (dedup within this scan by fingerprint)
    seen: set[str] = set()
    unique: list[Finding] = []
    for f in findings:
        if f.fingerprint not in seen:
            seen.add(f.fingerprint)
            unique.append(f)

    async with get_session_factory()() as session:
        session.add_all(
            [
                FindingRow(
                    id=uuid.uuid4(),
                    scan_id=uuid.UUID(state["scan_id"]),
                    tool=f.tool,
                    rule_id=f.rule_id,
                    severity=str(f.severity),
                    file_path=f.file_path,
                    start_line=f.start_line,
                    fingerprint=f.fingerprint,
                    raw=f.raw,
                )
                for f in unique
            ]
        )
        await session.commit()

    await log.ainfo(
        "scan complete",
        scan_id=state["scan_id"],
        total=len(findings),
        unique=len(unique),
    )
    return {
        "findings": unique,
        "events": [*events, f"scanner: {len(unique)} unique findings ({len(findings)} raw)"],
    }
