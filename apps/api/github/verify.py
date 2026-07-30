"""Webhook signature verification (HMAC-SHA256 over the raw request body)."""

import hashlib
import hmac

from core.config import get_settings


class SignatureError(Exception):
    pass


def verify_signature(body: bytes, signature_header: str | None) -> None:
    """Verify X-Hub-Signature-256. Raises SignatureError on any mismatch.

    Uses hmac.compare_digest against a hex digest computed over the *raw* bytes —
    parsing the body before verification would open canonicalization attacks.
    """
    if not signature_header:
        raise SignatureError("Missing X-Hub-Signature-256 header")

    secret = get_settings().github_webhook_secret
    if not secret:
        raise SignatureError("GITHUB_WEBHOOK_SECRET is not configured")

    if not signature_header.startswith("sha256="):
        raise SignatureError("Unexpected signature scheme")

    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise SignatureError("Signature mismatch")
