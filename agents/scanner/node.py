"""Scanner node — runs Semgrep + Gitleaks over the clone, normalizes findings."""

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


async def run_scanners(workdir: str) -> list[Finding]:
    """Both scanners in parallel; one failing doesn't sink the other."""
    semgrep = SemgrepRunner()
    gitleaks = GitleaksRunner()

    sarif_result, gitleaks_result = await asyncio.gather(
        asyncio.to_thread(semgrep.scan, workdir),
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
            findings.extend(parse_gitleaks(report))

    return findings


async def scanner_node(state: GuardianState) -> dict:
    findings = await run_scanners(state["workdir"])

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
        "events": [f"scanner: {len(unique)} unique findings ({len(findings)} raw)"],
    }
