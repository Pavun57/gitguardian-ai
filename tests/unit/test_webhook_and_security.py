"""Unit tests for webhook signature verification and core crypto/logging."""

import hashlib
import hmac

import pytest

from apps.api.github.verify import SignatureError, verify_signature
from core.config import get_settings
from core.logging import scrub_secrets


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def _webhook_secret(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_valid_signature_passes():
    body = b'{"zen": "hi"}'
    verify_signature(body, _sign(body, "test-secret"))


def test_wrong_secret_rejected():
    body = b'{"zen": "hi"}'
    with pytest.raises(SignatureError):
        verify_signature(body, _sign(body, "wrong-secret"))


def test_tampered_body_rejected():
    with pytest.raises(SignatureError):
        verify_signature(b'{"zen": "tampered"}', _sign(b'{"zen": "hi"}', "test-secret"))


def test_missing_header_rejected():
    with pytest.raises(SignatureError):
        verify_signature(b"{}", None)


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
