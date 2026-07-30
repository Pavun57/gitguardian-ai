"""Classifier node — severity ordering + LLM false-positive filter.

Severity is rule-based first (the scanners emit it); the cheap model only vets
likely false positives. An LLM failure here never blocks the pipeline — we fall
back to scanner severity alone.
"""

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


def sort_by_severity(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: SEVERITY_ORDER[f.severity])


async def filter_false_positives(
    findings: list[Finding], installation_id: int, state_cost: float
) -> tuple[list[Finding], float]:
    """Ask the cheap model which findings are likely FPs (e.g. test fixtures,
    example keys). Returns (kept_findings, cost_usd)."""
    settings = get_settings()
    check_budget(state_cost)

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
        "You are triaging static-analysis findings. For each finding below, decide if it is "
        "very likely a FALSE POSITIVE (test fixture, example/placeholder credential, "
        "documentation sample, intentionally vulnerable demo code under a fixtures/ or "
        "examples/ path).\n\n"
        "Reply with ONLY a comma-separated list of the indexes of the false positives, "
        "or the word NONE.\n\n"
        f"Findings:\n{summaries}"
    )

    conn = await resolve_agent(installation_id)
    if conn.provider == "anthropic":
        model = make_chat_model(settings.classify_model, conn.credential, temperature=0)
        resp = await model.ainvoke(prompt)
        tokens_in = resp.usage_metadata.get("input_tokens", 0) if resp.usage_metadata else 0
        tokens_out = resp.usage_metadata.get("output_tokens", 0) if resp.usage_metadata else 0
        cost = estimate_cost(settings.classify_model, tokens_in, tokens_out)
        text = resp.content
    else:
        backend = make_cli_backend(conn)
        resp = await backend.complete(prompt)
        cost = 0.0  # subscription-billed
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

    # LLM FP-filter is an enhancement, never a blocker
    try:
        findings, added = await filter_false_positives(findings, state["installation_id"], cost)
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
            f"classifier: {len(selected)} findings selected "
            f"(of {len(state['findings'])}), cost ${cost:.4f}"
        ],
    }
