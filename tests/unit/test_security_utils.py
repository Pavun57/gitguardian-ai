"""Unit tests for core security utilities (log scrubbing, crypto)."""

from core.logging import scrub_secrets


def test_scrubber_redacts_keys():
    event = {
        "key": "sk-ant-api03-abc123xyz",
        "gh": "ghp_" + "a" * 36,
        "nested": {"token": "x-access-token:secret123@github.com"},
        "safe": "hello",
    }
    out = scrub_secrets(None, "info", event)
    assert "sk-ant" not in str(out)
    assert "ghp_" not in str(out)
    assert "secret123" not in str(out)
    assert out["safe"] == "hello"


def test_scrubber_handles_nested_structures():
    event = {"list": ["sk-ant-secret-value-123", {"deep": "ghp_" + "b" * 40}]}
    out = scrub_secrets(None, "info", event)
    assert "sk-ant" not in str(out)
    assert "ghp_" not in str(out)
