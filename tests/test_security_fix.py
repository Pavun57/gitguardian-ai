"""Tests proving the hardcoded AWS API key was removed from main.py.

Stdlib only: fastapi is stubbed in sys.modules so the module can be
imported without any third-party packages installed.
"""
import asyncio
import importlib
import inspect
import os
import sys
import types
import unittest
from pathlib import Path

HARDCODED_KEY = "AWYJSPKNSHWIMOADFSC"
MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"


def _install_fastapi_stub():
    """Register a minimal fake `fastapi` module exposing FastAPI."""
    stub = types.ModuleType("fastapi")

    class FastAPI:  # noqa: D401 - minimal stand-in
        def __init__(self, *args, **kwargs):
            self.routes = {}

        def get(self, path):
            def decorator(func):
                self.routes[("GET", path)] = func
                return func

            return decorator

    stub.FastAPI = FastAPI
    sys.modules["fastapi"] = stub


def _import_fresh_main():
    sys.modules.pop("main", None)
    return importlib.import_module("main")


class HardcodedSecretTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_fastapi_stub()
        sys.path.insert(0, str(MODULE_PATH.parent))

    def setUp(self):
        self._old_env = os.environ.pop("AWS_API_KEY", None)

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("AWS_API_KEY", None)
        else:
            os.environ["AWS_API_KEY"] = self._old_env
        sys.modules.pop("main", None)

    def test_source_contains_no_hardcoded_secret(self):
        source = MODULE_PATH.read_text()
        self.assertNotIn(HARDCODED_KEY, source)

    def test_key_comes_from_environment(self):
        os.environ["AWS_API_KEY"] = "test-key-from-env"
        main = _import_fresh_main()
        self.assertEqual(main.aws_api_key, "test-key-from-env")

    def test_key_is_none_when_env_unset(self):
        main = _import_fresh_main()
        self.assertIsNone(main.aws_api_key)

    def test_no_credential_string_literal_assigned(self):
        """aws_api_key must not be assigned a string literal in source."""
        import ast

        tree = ast.parse(MODULE_PATH.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "aws_api_key":
                        self.assertFalse(
                            isinstance(node.value, ast.Constant)
                            and isinstance(node.value.value, str),
                            "aws_api_key is assigned a hardcoded string literal",
                        )

    def test_root_endpoint_uses_env_key(self):
        os.environ["AWS_API_KEY"] = "endpoint-test-key"
        main = _import_fresh_main()
        result = asyncio.run(main.root())
        self.assertEqual(result, {"message": "Hello World endpoint-test-key"})
        self.assertNotIn(HARDCODED_KEY, result["message"])


if __name__ == "__main__":
    unittest.main()
