"""Semgrep SARIF output → normalized Findings.

Hand-rolled rather than sarif-om: SARIF producers vary enough that defensive
.get() walking beats a strict object model here.
"""

import json

from core.schemas import Finding
from security.parsers.base import from_sarif


def parse_sarif(sarif_json: str | bytes | dict, repo_prefix: str = "/src/") -> list[Finding]:
    doc = json.loads(sarif_json) if isinstance(sarif_json, (str, bytes)) else sarif_json
    findings: list[Finding] = []

    for run in doc.get("runs", []):
        # ruleId → metadata severity lookup for this run
        rules_meta: dict[str, str] = {}
        for rule in (run.get("tool", {}).get("driver", {}) or {}).get("rules", []):
            props = rule.get("properties", {}) or {}
            sev = props.get("severity") or props.get("precision")
            if rule.get("id") and sev:
                rules_meta[rule["id"]] = sev

        for result in run.get("results", []):
            rule_id = result.get("ruleId", "unknown")
            level = result.get("level")
            message = (result.get("message") or {}).get("text", "")

            locations = result.get("locations") or []
            if not locations:
                continue
            phys = locations[0].get("physicalLocation") or {}
            artifact = (phys.get("artifactLocation") or {}).get("uri", "")
            region = phys.get("region") or {}

            path = artifact.removeprefix(repo_prefix).removeprefix("/")
            if not path:
                continue

            findings.append(
                Finding(
                    tool="semgrep",
                    rule_id=rule_id,
                    severity=from_sarif(level, rules_meta.get(rule_id)),
                    file_path=path,
                    start_line=region.get("startLine", 1),
                    end_line=region.get("endLine"),
                    message=message,
                    snippet=(region.get("snippet") or {}).get("text", ""),
                    raw=result,
                )
            )

    return findings
