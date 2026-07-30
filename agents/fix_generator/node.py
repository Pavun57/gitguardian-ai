"""Fix generation node — the connected coding agent produces a full-file
rewrite + a pytest suite.

Design (ADR-0001): full-file rewrite, not unified diff. Deterministically
applicable, trivially validatable. The fix AND test come from one call so they
share the model's understanding of intent.

Backends: 'anthropic' uses LangChain forced tool-use (guaranteed structure).
CLI backends (claude_code, codex) get the same schema embedded in the prompt;
their output is extracted and validated against the identical FixResult model.
"""

from pathlib import Path

from agents.backends import extract_json
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
from core.schemas import FixResult

log = get_logger("fix_generator")

FIX_TOOL = {
    "name": "submit_fix",
    "description": "Submit the complete fixed file and a pytest test suite proving the fix.",
    "input_schema": {
        "type": "object",
        "properties": {
            "explanation": {
                "type": "string",
                "description": "What the vulnerability is and how the fix addresses it "
                "(2-4 sentences).",
            },
            "fixed_file_content": {
                "type": "string",
                "description": "The COMPLETE content of the fixed file, from first to last line.",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "high: certain the fix is correct and complete. "
                "low: unsure — a human should take over.",
            },
            "test_file_content": {
                "type": "string",
                "description": "Complete pytest file. MUST use stdlib only (no pip installs), "
                "MUST import the fixed module via a relative path insert, and MUST exercise "
                "the vulnerable code path to prove it is now safe.",
            },
            "test_file_path": {
                "type": "string",
                "description": "Path for the test file, e.g. tests/test_security_fix.py",
            },
            "summary_for_pr": {
                "type": "string",
                "description": "One-line PR description summary.",
            },
        },
        "required": [
            "explanation",
            "fixed_file_content",
            "confidence",
            "test_file_content",
            "test_file_path",
            "summary_for_pr",
        ],
    },
}


def build_fix_prompt(
    finding, file_content: str, last_test_output: str | None, previous_fix: str | None
) -> str:
    numbered = "\n".join(f"{i + 1:4d} | {line}" for i, line in enumerate(file_content.splitlines()))
    retry_block = ""
    if last_test_output:
        retry_block = (
            "\n\n## Previous attempt failed\n"
            "Your previous fix's tests FAILED. Pytest output:\n"
            f"```\n{last_test_output[:4000]}\n```\n"
            "Fix the underlying issue, don't just make the test pass artificially."
        )
    return f"""You are a senior security engineer fixing a vulnerability.

## Finding
- Rule: {finding.rule_id} (tool: {finding.tool}, severity: {finding.severity})
- File: {finding.file_path}, line {finding.start_line}
- Message: {finding.message}

## Current file content (line numbers for reference — do not include them in your output)
```
{numbered}
```

## Requirements
1. Return the COMPLETE fixed file (no truncation, no placeholders like "// rest unchanged").
2. Make the minimal change that removes the vulnerability. Preserve all existing behavior.
3. Never hardcode a replacement secret — use environment variables / config injection.
4. Write a pytest suite (stdlib only, no network, no pip installs) that imports the fixed
   module and proves the vulnerable path is now safe. The suite must pass.
5. If you are not confident the fix is correct, set confidence to "low" — a human will
   take over instead of a bad fix shipping.
{retry_block}"""


_CLI_SCHEMA_INSTRUCTION = """

## Output format (strict)
Respond with ONLY a JSON object (no markdown fences, no prose) with exactly these keys:
{
  "explanation": "what the vulnerability is and how the fix addresses it (2-4 sentences)",
  "fixed_file_content": "the COMPLETE fixed file content",
  "confidence": "high" | "medium" | "low",
  "test_file_content": "complete pytest file (stdlib only)",
  "test_file_path": "e.g. tests/test_security_fix.py",
  "summary_for_pr": "one-line PR summary"
}"""


async def _generate_via_anthropic(state: GuardianState, prompt: str, credential: str):
    """LangChain forced tool-use — guaranteed structured output.

    Fallback: some gateways enable extended thinking by default, which forbids
    named tool_choice ("specified"). On that 400, retry with tool_choice=auto
    and a prompt instruction making the tool call mandatory.
    """
    settings = get_settings()
    model = make_chat_model(settings.fix_model, credential, temperature=0.2)

    try:
        forced = model.bind_tools([FIX_TOOL], tool_choice={"type": "tool", "name": "submit_fix"})
        resp = await forced.ainvoke(prompt)
    except Exception as e:
        if "tool_choice" not in str(e):
            raise
        auto = model.bind_tools([FIX_TOOL], tool_choice={"type": "auto"})
        resp = await auto.ainvoke(
            prompt + "\n\nYou MUST respond by calling the submit_fix tool — no plain text."
        )

    tokens_in = resp.usage_metadata.get("input_tokens", 0) if resp.usage_metadata else 0
    tokens_out = resp.usage_metadata.get("output_tokens", 0) if resp.usage_metadata else 0
    cost = estimate_cost(settings.fix_model, tokens_in, tokens_out)

    if not resp.tool_calls:
        raise ValueError("model returned no tool call")
    return resp.tool_calls[0]["args"], cost, tokens_in, tokens_out


async def _generate_via_cli(state: GuardianState, prompt: str, conn):
    """Installed coding agent (claude_code / codex) — schema in prompt, JSON out."""
    backend = make_cli_backend(conn)
    resp = await backend.complete(prompt + _CLI_SCHEMA_INSTRUCTION)
    args = extract_json(resp.text)
    # Claude Code reports real cost in its envelope; otherwise estimate from tokens
    cost = resp.cost_usd or estimate_cost(get_settings().fix_model, resp.tokens_in, resp.tokens_out)
    return args, cost, resp.tokens_in, resp.tokens_out


async def generate_fix(state: GuardianState) -> tuple[FixResult, float, int, int]:
    """One agent call → FixResult + (cost, tokens_in, tokens_out)."""
    settings = get_settings()
    finding = state["current_finding"]
    workdir = Path(state["workdir"])
    target = workdir / finding.file_path

    file_content = target.read_text(errors="replace")
    if len(file_content.splitlines()) > settings.max_file_lines:
        raise ValueError(f"file too large ({len(file_content.splitlines())} lines)")

    check_budget(state.get("llm_cost_usd", 0.0))

    conn = await resolve_agent(state["installation_id"])
    prompt = build_fix_prompt(
        finding,
        file_content,
        state.get("last_test_output"),
        state["fix"].fixed_file_content if state.get("fix") else None,
    )

    if conn.provider == "anthropic":
        args, cost, tin, tout = await _generate_via_anthropic(state, prompt, conn.credential)
    else:
        args, cost, tin, tout = await _generate_via_cli(state, prompt, conn)

    return FixResult(**args), cost, tin, tout


async def fix_generator_node(state: GuardianState) -> dict:
    fix, cost, tin, tout = await generate_fix(state)
    await log.ainfo(
        "fix generated",
        rule=state["current_finding"].rule_id,
        confidence=fix.confidence,
        cost_usd=cost,
    )
    return {
        "fix": fix,
        "llm_cost_usd": state.get("llm_cost_usd", 0.0) + cost,
        "llm_input_tokens": state.get("llm_input_tokens", 0) + tin,
        "llm_output_tokens": state.get("llm_output_tokens", 0) + tout,
        "events": [
            f"fix_generator: fix for {state['current_finding'].rule_id} "
            f"(confidence {fix.confidence})"
        ],
    }
