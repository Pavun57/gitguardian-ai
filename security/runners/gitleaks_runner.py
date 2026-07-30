"""Gitleaks runner — filesystem-mode secret scan in a sibling container."""

import tempfile
from pathlib import Path

from core.config import get_settings
from core.logging import get_logger
from security.runners.docker_base import DockerRunner

log = get_logger("gitleaks")


class GitleaksRunner:
    def __init__(self, runner: DockerRunner | None = None):
        self.runner = runner or DockerRunner()
        self.image = get_settings().gitleaks_image

    def scan(self, repo_path: str) -> tuple[str | None, str | None]:
        """Run gitleaks in filesystem mode. Returns (report_json, error).

        Filesystem mode (--no-git) scans the working tree as-is — right for
        checking a push's checked-out state. Git-history mode is a later phase.
        """
        settings = get_settings()

        out_dir = tempfile.mkdtemp(prefix="gg-gitleaks-out-")
        Path(out_dir).chmod(0o777)  # container runs as uid 1000, dir is created by the worker
        try:
            result = self.runner.run_hardened(
                image=self.image,
                command=[
                    "detect",
                    "--source",
                    "/work",
                    "--no-git",
                    "--report-format",
                    "json",
                    "--report-path",
                    "/out/report.json",
                    "--exit-code",
                    "0",  # findings are data, not an error
                ],
                workdir_host_path=repo_path,
                output_dir_host_path=out_dir,
                timeout=settings.scan_timeout_seconds,
                env={"HOME": "/tmp"},  # noqa: S108 - container path, not host
            )

            report = Path(out_dir) / "report.json"
            if not report.exists():
                # No findings → gitleaks may not write the report at all
                if result.exit_code == 0:
                    return "[]", None
                return None, result.error or result.output[-2000:]
            return report.read_text() or "[]", None
        finally:
            import shutil

            shutil.rmtree(out_dir, ignore_errors=True)
