"""Gitleaks JSON report → normalized Findings.

Gitleaks emits a flat JSON array. Secret values are stripped from what we store —
the raw record is redacted before it can reach the DB or an LLM prompt.
"""

import json

from core.schemas import Finding
from security.parsers.base import from_gitleaks

_REDACT = "***REDACTED***"


def parse_gitleaks(report_json: str | bytes | list) -> list[Finding]:
    records = json.loads(report_json) if isinstance(report_json, (str, bytes)) else report_json
    if isinstance(records, dict):  # empty scan → some versions emit {}
        records = records.get("findings", [])

    findings: list[Finding] = []
    for rec in records or []:
        redacted = {**rec}
        for key in ("Secret", "Match", "Line"):
            if key in redacted:
                redacted[key] = _REDACT

        findings.append(
            Finding(
                tool="gitleaks",
                rule_id=rec.get("RuleID", "unknown"),
                severity=from_gitleaks(rec),
                file_path=rec.get("File", "").removeprefix("/work/").removeprefix("/"),
                start_line=rec.get("StartLine", 1),
                end_line=rec.get("EndLine"),
                message=f"Exposed secret ({rec.get('RuleID', 'unknown')})",
                snippet="",  # never carry the matched line — it contains the secret
                raw=redacted,
            )
        )

    return findings
