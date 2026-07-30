"""LangGraph pipeline — the heart of GitGuardian.

One invocation handles one push. Topology:

  router → scanner → classifier
    → no findings → finalize → notify → END
    → findings    → fix_select → fix_generate → fix_apply → test_run
                      ▲   │                        │           │
                      │   │ low confidence         │ invalid   │ tests failed
                      │   └──────┐  ┌──────────────┘           │ (attempts < max)
                      │          ▼  ▼                          ▼
                      │       fix_advance ──────────────── retry → fix_generate
                      │          │  tests passed → pr_create → fix_advance
                      ▼          ▼  more findings → fix_select
                   finalize → notify → END

Guardrails: MAX_FINDINGS_PER_SCAN selection happens in classifier; MAX_FIX_ATTEMPTS
and the dollar budget are enforced here and in agents/llm.py.
"""

from langgraph.graph import END, StateGraph

from agents.classifier.node import classifier_node
from agents.fix_generator.apply import FixValidationError, apply_fix, validate_with_rescan
from agents.fix_generator.node import fix_generator_node
from agents.notify.node import notify_node
from agents.pr_creator.node import pr_creator_node
from agents.router.node import router_node
from agents.scanner.node import scanner_node
from agents.state import GuardianState
from agents.test_generator.runner_node import test_generator_node
from core.config import get_settings
from core.logging import get_logger

log = get_logger("graph")


# --- glue nodes -------------------------------------------------------------


async def fix_select_node(state: GuardianState) -> dict:
    idx = state.get("findings_index", 0)
    finding = state["findings"][idx]
    return {
        "current_finding": finding,
        "fix_attempts": 0,
        "fix": None,
        "test_result": None,
        "last_test_output": None,
        "events": [f"fix_select: [{idx + 1}/{len(state['findings'])}] {finding.rule_id}"],
    }


async def fix_apply_node(state: GuardianState) -> dict:
    """Apply + validate the fix. Validation failures become retry context."""
    try:
        await apply_fix(state["workdir"], state["current_finding"], state["fix"])
        await validate_with_rescan(state["workdir"], state["current_finding"])
    except FixValidationError as e:
        attempts = state.get("fix_attempts", 0) + 1
        await log.awarning("fix validation failed", error=str(e), attempts=attempts)
        return {
            "fix_attempts": attempts,
            "last_test_output": f"Fix REJECTED by validator: {e}",
            "events": [f"fix_apply: validation failed ({e})"],
        }
    return {"events": ["fix_apply: applied + re-scan clean"]}


async def fix_advance_node(state: GuardianState) -> dict:
    return {"findings_index": state.get("findings_index", 0) + 1}


async def finalize_node(state: GuardianState) -> dict:
    """Persist final scan status + cost; best-effort check-run for clean scans
    happens in notify. Never raises."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    from core.db.models import Scan
    from core.db.session import get_session_factory

    prs = state.get("prs", [])
    findings = state.get("findings", [])
    status = "no_findings" if not findings else ("awaiting_review" if prs else "completed")
    try:
        async with get_session_factory()() as session:
            scan = await session.scalar(select(Scan).where(Scan.id == state["scan_id"]))
            if scan:
                scan.status = status
                scan.llm_cost_usd = state.get("llm_cost_usd", 0.0)
                scan.finished_at = datetime.now(UTC)
                if state.get("error"):
                    scan.error = state["error"]
            await session.commit()
    except Exception as e:
        await log.aerror("finalize failed (swallowed)", error=str(e)[:300])
    return {"events": [f"finalize: status={status}"]}


# --- conditional edges --------------------------------------------------------


def after_classify(state: GuardianState) -> str:
    return "fix_select" if state.get("findings") else "finalize"


def after_fix_generate(state: GuardianState) -> str:
    if state.get("fix") and state["fix"].confidence == "low":
        return "fix_advance"  # never open a PR for a low-confidence fix
    return "fix_apply"


def after_fix_apply(state: GuardianState) -> str:
    # Validation failure recorded in last_test_output with a bump in attempts
    if (state.get("last_test_output") or "").startswith("Fix REJECTED"):
        if state.get("fix_attempts", 0) < get_settings().max_fix_attempts:
            return "fix_generate"
        return "fix_advance"
    return "test_run"


def after_test_run(state: GuardianState) -> str:
    result = state.get("test_result")
    if result and result.passed:
        return "pr_create"
    if state.get("fix_attempts", 0) < get_settings().max_fix_attempts:
        return "fix_generate"  # retry with pytest output as context
    return "fix_advance"  # out of attempts — human takes over


def after_advance(state: GuardianState) -> str:
    if state.get("findings_index", 0) < len(state.get("findings", [])):
        return "fix_select"
    return "finalize"


# --- graph --------------------------------------------------------------------


def build_graph(checkpointer=None):
    g = StateGraph(GuardianState)

    g.add_node("router", router_node)
    g.add_node("scanner", scanner_node)
    g.add_node("classifier", classifier_node)
    g.add_node("fix_select", fix_select_node)
    g.add_node("fix_generate", fix_generator_node)
    g.add_node("fix_apply", fix_apply_node)
    g.add_node("test_run", test_generator_node)
    g.add_node("pr_create", pr_creator_node)
    g.add_node("fix_advance", fix_advance_node)
    g.add_node("finalize", finalize_node)
    g.add_node("notify", notify_node)

    g.set_entry_point("router")
    g.add_edge("router", "scanner")
    g.add_edge("scanner", "classifier")
    g.add_conditional_edges("classifier", after_classify)
    g.add_edge("fix_select", "fix_generate")
    g.add_conditional_edges("fix_generate", after_fix_generate)
    g.add_conditional_edges("fix_apply", after_fix_apply)
    g.add_conditional_edges("test_run", after_test_run)
    g.add_edge("pr_create", "fix_advance")
    g.add_conditional_edges("fix_advance", after_advance)
    g.add_edge("finalize", "notify")
    g.add_edge("notify", END)

    return g.compile(checkpointer=checkpointer)
