"""Security regression tests for the hardcoded-secret finding in main.py.

Stdlib only: fastapi is stubbed in sys.modules before importing main so the
module can be imported and exercised without the third-party dependency.
"""
import asyncio
import importlib
import os
import re
import sys
import types
from pathlib import Path

import pytest


class _StubFastAPI:
    """Minimal stand-in for fastapi.FastAPI (app + route decorator)."""

    def __init__(self, *args, **kwargs):
        self.routes = {}

    def get(self, path):
        def decorator(func):
            self.routes[path] = func
            return func

        return decorator


@pytest.fixture()
def fastapi_stub(monkeypatch):
    module = types.ModuleType("fastapi")
    module.FastAPI = _StubFastAPI
    monkeypatch.setitem(sys.modules, "fastapi", module)
    return module


def _import_main(monkeypatch, env_value):
    if env_value is None:
        monkeypatch.delenv("AWS_API_KEY", raising=False)
    else:
        monkeypatch.setenv("AWS_API_KEY", env_value)
    sys.modules.pop("main", None)
    return importlib.import_module("main")


def test_source_contains_no_hardcoded_secret(fastapi_stub):
    source = Path("main.py").read_text(encoding="utf-8")
    # The credential must come from the environment, never a string literal.
    assert 'os.environ.get("AWS_API_KEY"' in source
    assert re.search(r'AWS_API_KEY"\s*,\s*["\'][^"\']+["\']', source) is None


def test_key_is_read_from_environment(fastapi_stub, monkeypatch):
    sentinel = "test-env-value-12345"
    main = _import_main(monkeypatch, sentinel)
    assert main.aws_api_key == sentinel


def test_key_defaults_to_empty_when_env_missing(fastapi_stub, monkeypatch):
    main = _import_main(monkeypatch, None)
    assert main.aws_api_key == ""


def test_root_response_does_not_leak_key(fastapi_stub, monkeypatch):
    sentinel = "super-secret-key-must-not-leak"
    main = _import_main(monkeypatch, sentinel)
    response = asyncio.run(main.root())
    assert sentinel not in str(response)
    assert response == {"message": "Hello World"}
