"""Agent backends — how the fix/classifier agents actually reach a model.

Three backends, selected per installation via the dashboard:

  anthropic_api  — BYOK: user's Anthropic API key (or env fallback). LangChain
                   forced tool-use gives us guaranteed structured output.
  claude_code    — user's installed Claude Code subscription. Headless mode:
                   `claude -p` with CLAUDE_CODE_OAUTH_TOKEN (from `claude
                   setup-token`). No API key — the user's plan is billed.
  codex          — user's installed Codex CLI: `codex exec` with OPENAI_API_KEY
                   or ChatGPT auth (auth.json pasted in the dashboard).

CLI backends can't do forced tool-use, so they receive the JSON schema in the
prompt and their output is extracted + validated against the same FixResult
model — the rest of the pipeline never knows the difference.
"""

import asyncio
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.logging import get_logger

log = get_logger("agent_backends")


@dataclass
class AgentResponse:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


class AgentBackend(ABC):
    """One LLM call, in any flavor."""

    @abstractmethod
    async def complete(self, prompt: str, *, max_tokens: int = 8192) -> AgentResponse: ...

    @property
    @abstractmethod
    def model_label(self) -> str: ...


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of CLI output (handles prose + fences)."""
    # Try fenced block first, then raw document, then first {...} span
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : i + 1])
                    break
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
    raise ValueError(f"no valid JSON in agent output ({len(text)} chars)")


class ClaudeCodeBackend(AgentBackend):
    """Headless Claude Code: `claude -p` with the user's OAuth token."""

    def __init__(self, oauth_token: str, model: str | None = None):
        self._token = oauth_token
        self._model = model

    @property
    def model_label(self) -> str:
        return f"claude-code:{self._model or 'default'}"

    async def complete(self, prompt: str, *, max_tokens: int = 8192) -> AgentResponse:
        import os

        env = {
            **os.environ,
            "CLAUDE_CODE_OAUTH_TOKEN": self._token,
        }
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        if self._model:
            cmd += ["--model", self._model]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI failed: {stderr.decode()[:500]}")

        # --output-format json wraps the result; extract usage + text
        try:
            envelope = json.loads(stdout.decode())
            usage = envelope.get("usage", {})
            return AgentResponse(
                text=envelope.get("result", ""),
                tokens_in=usage.get("input_tokens", 0),
                tokens_out=usage.get("output_tokens", 0),
            )
        except json.JSONDecodeError:
            return AgentResponse(text=stdout.decode())


def _write_file(path: str, content: str) -> None:
    from pathlib import Path

    Path(path).write_text(content)


class CodexBackend(AgentBackend):
    """Headless Codex CLI: `codex exec`."""

    def __init__(self, credential: str, model: str | None = None):
        # credential: OPENAI_API_KEY value, or full auth.json content
        self._credential = credential
        self._model = model

    @property
    def model_label(self) -> str:
        return f"codex:{self._model or 'default'}"

    async def complete(self, prompt: str, *, max_tokens: int = 8192) -> AgentResponse:
        import os

        env = dict(os.environ)
        cmd = ["codex", "exec", "--json", "--skip-git-repo-check"]
        if self._model:
            cmd += ["--model", self._model]

        if self._credential.strip().startswith("{"):
            # ChatGPT auth.json — write to a temp CODEX_HOME
            import tempfile

            codex_home = tempfile.mkdtemp(prefix="gg-codex-")
            auth_path = f"{codex_home}/auth.json"
            await asyncio.to_thread(_write_file, auth_path, self._credential)
            env["CODEX_HOME"] = codex_home
        else:
            env["OPENAI_API_KEY"] = self._credential

        cmd.append(prompt)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"codex CLI failed: {stderr.decode()[:500]}")

        # --json emits JSONL events; the agent's reply is in the last message event
        text = ""
        for line in stdout.decode().splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") in ("item.completed", "message"):
                item = event.get("item") or event
                if item.get("type") == "agent_message" or item.get("role") == "assistant":
                    text = item.get("text") or item.get("content", "")
        return AgentResponse(text=text or stdout.decode()[-8000:])
