"""Classifier node — severity ordering + false-positive filtering.

Two layers, most-conservative-first:
  1. Deterministic: findings under fixture/example/dataset paths are dropped
     by rule — no model judgment involved.
  2. LLM: vets the rest for likely FPs with a KEEP-when-in-doubt prompt.
An LLM failure here never blocks the pipeline — we fall back to scanner
severity alone.
"""

import re

from agents.llm import (
    check_budget,
    estimate_cost,
    make_chat_model,
    make_cli_backend,
    resolve_agent,
)
from agents.state import GuardianState
from core.config import get_settings
from core.logging import get_logger
from core.schemas import SEVERITY_ORDER, Finding

log = get_logger("classifier")

# Paths that are test fixtures, example code, or eval datasets — findings here
# are intentionally vulnerable content, not real risk.
FIXTURE_PATH_RE = re.compile(
    r"(^|/)(fixtures?|examples?|samples?|testdata|test_data|datasets?|"
    r"__fixtures__|mocks?)(/|$)|(^|/)evals/|(^|/)benchmarks?/",
    re.IGNORECASE,
)


def drop_fixture_findings(findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """Split into (kept, dropped-by-path-rule)."""
    kept = [f for f in findings if not FIXTURE_PATH_RE.search(f.file_path)]
    dropped = [f for f in findings if FIXTURE_PATH_RE.search(f.file_path)]
    return kept, dropped


def sort_by_severity(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: SEVERITY_ORDER[f.severity])


def _resp_text(content) -> str:
    """ChatAnthropic content may be a string or a list of content blocks."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif hasattr(block, "text"):
            parts.append(block.text)
    return "".join(parts)


async def filter_false_positives(
    findings: list[Finding], state_cost: float
) -> tuple[list[Finding], float]:
    """Ask the cheap model which findings are likely FPs (e.g. test fixtures,
    example keys). Returns (kept_findings, cost_usd)."""
    settings = get_settings()

    summaries = [
        {
            "i": i,
            "rule": f.rule_id,
            "file": f.file_path,
            "line": f.start_line,
            "severity": str(f.severity),
            "message": f.message[:200],
        }
        for i, f in enumerate(findings)
    ]
    prompt = (
        "You are triaging static-analysis security findings for a repository.\n"
        "Decide which findings are CLEARLY false positives.\n\n"
        "Rules:\n"
        "- Only flag a finding if the finding itself is clearly not exploitable "
        "(e.g. a lockfile hash match, a comment mentioning a pattern, an obvious "
        "documentation snippet).\n"
        "- NEVER flag a finding just because a credential 'looks fake' or the repo "
        "looks like a demo — real leaks often look like that.\n"
        "- When in doubt, DO NOT flag it. Keeping a real finding is always the "
        "correct default.\n\n"
        "Reply with ONLY a comma-separated list of the indexes to drop, "
        "or the word NONE.\n\n"
        f"Findings:\n{summaries}"
    )

    conn = await resolve_agent()
    check_budget(state_cost, metered=conn.is_metered)
    if conn.provider == "anthropic":
        model = make_chat_model(settings.classify_model, conn.credential, temperature=0)
        resp = await model.ainvoke(prompt)
        tokens_in = resp.usage_metadata.get("input_tokens", 0) if resp.usage_metadata else 0
        tokens_out = resp.usage_metadata.get("output_tokens", 0) if resp.usage_metadata else 0
        cost = estimate_cost(settings.classify_model, tokens_in, tokens_out)
        text = _resp_text(resp.content)
    else:
        backend = make_cli_backend(conn)
        resp = await backend.complete(prompt)
        cost = resp.cost_usd or estimate_cost(
            settings.classify_model, resp.tokens_in, resp.tokens_out
        )
        text = resp.text

    text = text.strip().upper()
    if "NONE" in text:
        return findings, cost

    try:
        fp_indexes = {
            int(t.strip()) for t in text.replace(".", "").split(",") if t.strip().isdigit()
        }
    except ValueError:
        return findings, cost

    kept = [f for i, f in enumerate(findings) if i not in fp_indexes]
    await log.ainfo("FP filter", dropped=len(findings) - len(kept), cost_usd=cost)
    return kept, cost


async def classifier_node(state: GuardianState) -> dict:
    settings = get_settings()
    findings = sort_by_severity(state["findings"])
    cost = state.get("llm_cost_usd", 0.0)

    # Layer 1: deterministic fixture-path drop
    findings, path_dropped = drop_fixture_findings(findings)
    if path_dropped:
        await log.ainfo(
            "fixture-path findings dropped",
            count=len(path_dropped),
            files=sorted({f.file_path for f in path_dropped})[:10],
        )

    # Layer 2: LLM FP-filter (enhancement, never a blocker)
    if findings:
        try:
            findings, added = await filter_false_positives(findings, cost)
            cost += added
        except Exception as e:
            await log.awarning("FP filter skipped", error=str(e)[:300])

    selected = findings[: settings.max_findings_per_scan]
    if len(findings) > len(selected):
        await log.ainfo("findings capped", total=len(findings), selected=len(selected))

    return {
        "findings": selected,
        "findings_index": 0,
        "llm_cost_usd": cost,
        "events": [
            f"classifier: {len(selected)} selected (of {len(state['findings'])} raw, "
            f"{len(path_dropped)} fixture-path dropped), cost ${cost:.4f}"
        ],
    }
