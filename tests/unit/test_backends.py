"""Unit tests for agent backends: JSON extraction + resolution."""

import pytest

from agents.backends import extract_json
from agents.llm import AgentConnection, ClaudeCodeBackend, CodexBackend, make_cli_backend


def test_extract_plain_json():
    assert extract_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_extract_fenced_json():
    text = 'Here is the fix:\n```json\n{"explanation": "e", "confidence": "high"}\n```\nDone.'
    assert extract_json(text) == {"explanation": "e", "confidence": "high"}


def test_extract_json_with_surrounding_prose():
    text = 'Sure! {"explanation": "e", "fixed_file_content": "line1\\nline2"} hope this helps'
    assert extract_json(text)["fixed_file_content"] == "line1\nline2"


def test_extract_nested_braces():
    text = '{"outer": {"inner": [1, 2, {"deep": true}]}, "n": 3}'
    assert extract_json(text)["outer"]["inner"][2]["deep"] is True


def test_extract_raises_on_garbage():
    with pytest.raises(ValueError, match="no valid JSON"):
        extract_json("no json here at all")


def test_make_cli_backend_claude_code():
    conn = AgentConnection("claude_code", "sk-ant-oat-test")
    backend = make_cli_backend(conn)
    assert isinstance(backend, ClaudeCodeBackend)
    assert "claude-code" in backend.model_label


def test_make_cli_backend_codex():
    conn = AgentConnection("codex", "sk-test")
    backend = make_cli_backend(conn)
    assert isinstance(backend, CodexBackend)


def test_make_cli_backend_rejects_api_provider():
    with pytest.raises(ValueError):
        make_cli_backend(AgentConnection("anthropic", "sk-ant-x"))


def test_metered_flag():
    assert AgentConnection("anthropic", "k").is_metered
    assert not AgentConnection("claude_code", "k").is_metered
    assert not AgentConnection("codex", "k").is_metered
