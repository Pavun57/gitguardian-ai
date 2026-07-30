"""Test execution node — runs the generated pytest suite in a hardened container.

The workspace is COPIED (not the live clone) and mounted read-only; the
container has no network, capped CPU/RAM/PIDs, non-root user, no capabilities.
"""

import asyncio
import os
import shutil
import tempfile

from agents.state import GuardianState
from core.config import get_settings
from core.logging import get_logger
from core.schemas import TestResult
from security.runners.docker_base import DockerRunner

log = get_logger("test_runner")

OUTPUT_TAIL = 4000  # chars of pytest output fed back into the fix prompt on retry


async def run_tests(workdir: str, test_file_path: str) -> TestResult:
    settings = get_settings()
    runner = DockerRunner()

    sandbox = tempfile.mkdtemp(prefix="gg-test-")
    os.chmod(sandbox, 0o755)  # noqa: S103 - container uid 1000 must read it
    try:
        # Copy the patched tree (exclude .git) so the live clone is never exposed
        shutil.copytree(
            workdir,
            sandbox,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".git"),
        )

        result = await asyncio.to_thread(
            runner.run_hardened,
            image=settings.test_runner_image,
            command=[test_file_path, "-x", "-q", "--timeout=60", "-p", "no:cacheprovider"],
            workdir_host_path=sandbox,
            timeout=settings.test_timeout_seconds,
        )

        output = (result.output or "")[-OUTPUT_TAIL:]
        return TestResult(
            passed=result.exit_code == 0 and not result.timed_out and not result.error,
            output=output,
            duration_seconds=result.duration_seconds,
            timed_out=result.timed_out,
        )
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


async def test_generator_node(state: GuardianState) -> dict:
    result = await run_tests(state["workdir"], state["fix"].test_file_path)
    attempts = state.get("fix_attempts", 0) + (0 if result.passed else 1)

    await log.ainfo(
        "tests run",
        rule=state["current_finding"].rule_id,
        passed=result.passed,
        duration=round(result.duration_seconds, 1),
    )
    return {
        "test_result": result,
        "fix_attempts": attempts,
        "last_test_output": None if result.passed else result.output,
        "events": [
            f"test_generator: {'PASSED' if result.passed else 'FAILED'} "
            f"in {result.duration_seconds:.1f}s"
        ],
    }
