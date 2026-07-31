"""Semgrep runner — scans a repo tree in a sibling container, returns SARIF."""

import tempfile
from pathlib import Path

from core.config import get_settings
from core.logging import get_logger
from security.runners.docker_base import DockerRunner

log = get_logger("semgrep")

_RULES_DIR = Path(__file__).resolve().parent.parent / "rules" / "semgrep"


class SemgrepRunner:
    def __init__(self, runner: DockerRunner | None = None):
        self.runner = runner or DockerRunner()
        self.image = get_settings().semgrep_image

    def scan(
        self, repo_path: str, target_files: list[str] | None = None
    ) -> tuple[str | None, str | None]:
        """Run semgrep over repo_path (or specific files). Returns (sarif_json, error).

        The workspace is mounted read-only; the SARIF report goes to a rw /out mount.
        """
        settings = get_settings()
        targets = target_files or ["."]

        out_dir = tempfile.mkdtemp(prefix="gg-semgrep-out-")
        Path(out_dir).chmod(0o777)  # container runs as uid 1000, dir is created by the worker
        try:
            result = self.runner.run_hardened(
                image=self.image,
                # No registry configs (p/default etc.) — the container has no network.
                # Local custom rules only; the trade-off is documented in the README.
                command=[
                    "semgrep",
                    "scan",
                    "--sarif",
                    "--output",
                    "/out/report.sarif",
                    "--config",
                    "/gitguardian",
                    "--metrics",
                    "off",
                    "--no-git-ignore",
                    *targets,
                ],
                workdir_host_path=repo_path,
                output_dir_host_path=out_dir,
                rules_host_path=str(_RULES_DIR),
                timeout=settings.scan_timeout_seconds,
                mem_limit="1g",
                cpu_quota=2.0,
                # semgrep needs a writable HOME for its cache; /tmp is a noexec tmpfs
                # /tmp is a container path, not host
                env={"HOME": "/tmp", "SEMGREP_USER_AGENT": "gitguardian-ai"},  # noqa: S108
            )

            report = Path(out_dir) / "report.sarif"
            if not report.exists():
                return None, result.error or result.output[-2000:] or "no SARIF report produced"
            content = report.read_text()
            if not content.strip():
                return None, "empty SARIF output"
            return content, None
        finally:
            import shutil

            shutil.rmtree(out_dir, ignore_errors=True)
