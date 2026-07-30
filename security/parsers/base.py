"""Severity normalization shared by all parsers.

Tools disagree on severity vocabularies; everything collapses into core.schemas.Severity.
"""

from core.schemas import Severity

_SARIF_LEVEL_MAP = {
    "error": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "note": Severity.LOW,
    "none": Severity.LOW,
}

# Semgrep metadata severity (more precise than SARIF level when present)
_SEMGREP_META_MAP = {
    "critical": Severity.CRITICAL,
    "error": Severity.HIGH,
    "high": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "medium": Severity.MEDIUM,
    "info": Severity.LOW,
    "low": Severity.LOW,
}


def from_sarif(level: str | None, meta_severity: str | None = None) -> Severity:
    if meta_severity and meta_severity.lower() in _SEMGREP_META_MAP:
        return _SEMGREP_META_MAP[meta_severity.lower()]
    return _SARIF_LEVEL_MAP.get((level or "").lower(), Severity.MEDIUM)


def from_gitleaks(_raw: dict) -> Severity:
    # Gitleaks findings are exposed secrets: always high-impact.
    return Severity.CRITICAL
