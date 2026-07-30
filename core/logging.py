"""Structlog setup with secret scrubbing.

Two scrub rules, applied from day one:
  - Anthropic API keys (sk-ant-*) must never reach logs.
  - GitHub tokens (ghp_*, ghs_*, ghu_*, github_pat_*, x-access-token values) likewise.
"""

import logging
import re
import sys

import structlog

_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9\-_]+"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(x-access-token:)[^@\s]+"),
]

_REDACTED = "***REDACTED***"


def scrub_secrets(logger: logging.Logger, name: str, event_dict: dict) -> dict:
    """Structlog processor: redact secret-looking values anywhere in the event."""

    def _scrub(value):
        if isinstance(value, str):
            for pat in _SECRET_PATTERNS:
                if pat.pattern.startswith("(x-access-token:)"):
                    value = pat.sub(r"\1" + _REDACTED, value)
                else:
                    value = pat.sub(_REDACTED, value)
            return value
        if isinstance(value, dict):
            return {k: _scrub(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return type(value)(_scrub(v) for v in value)
        return value

    return {k: _scrub(v) for k, v in event_dict.items()}


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            scrub_secrets,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
