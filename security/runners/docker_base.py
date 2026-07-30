"""Hardened sibling-container runner.

All untrusted work (scanners over arbitrary repos, LLM-generated pytest suites)
runs in sibling containers spawned via the mounted Docker socket. The worker is
trusted; these containers are the security boundary:

  - --network none        no exfiltration, no package downloads
  - read-only root FS     + small noexec tmpfs for pytest cache/bytecode
  - non-root user, cap-drop ALL, no-new-privileges
  - memory / CPU / PID caps
  - hard wall-clock timeout; container is always killed and removed

See docs/architecture/ADR-0002. Production hardening path: gVisor/Firecracker.
"""

import time
from dataclasses import dataclass, field

import docker
from docker.errors import APIError, ContainerError, ImageNotFound

from core.logging import get_logger

log = get_logger("docker_runner")


@dataclass
class ContainerResult:
    exit_code: int
    output: str  # combined stdout+stderr, truncated
    duration_seconds: float
    timed_out: bool = False
    error: str | None = field(default=None)


class DockerRunner:
    def __init__(self, client: docker.DockerClient | None = None):
        self._client = client or docker.from_env()

    def run_hardened(
        self,
        image: str,
        command: list[str],
        workdir_host_path: str,
        container_workdir: str = "/work",
        timeout: int = 120,
        network_none: bool = True,
        mem_limit: str = "512m",
        cpu_quota: float = 1.0,
        output_max_bytes: int = 64_000,
        env: dict[str, str] | None = None,
        output_dir_host_path: str | None = None,
        rules_host_path: str | None = None,
    ) -> ContainerResult:
        """Run `command` in a hardened container with the workspace mounted read-only.

        output_dir_host_path: optional host dir mounted rw at /out (scanner reports).
        rules_host_path: optional host dir mounted ro at /rules (custom semgrep rules).
        """
        start = time.monotonic()
        container = None
        volumes: dict = {workdir_host_path: {"bind": container_workdir, "mode": "ro"}}
        if output_dir_host_path:
            volumes[output_dir_host_path] = {"bind": "/out", "mode": "rw"}
        if rules_host_path:
            # Mounted at /gitguardian so semgrep namespaces rules as
            # "gitguardian.<rule-id>" (namespace = mount dir basename).
            volumes[rules_host_path] = {"bind": "/gitguardian", "mode": "ro"}
        try:
            container = self._client.containers.create(
                image,
                command=command,
                volumes=volumes,
                working_dir=container_workdir,
                network_disabled=network_none,
                mem_limit=mem_limit,
                nano_cpus=int(cpu_quota * 1e9),
                pids_limit=128,
                read_only=True,
                tmpfs={"/tmp": "rw,noexec,nosuid,size=64m"},  # noqa: S108 - container path, not host
                user="1000:1000",
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                environment=env or {},
                detach=True,
            )
            container.start()
            result = container.wait(timeout=timeout)
            logs = container.logs(stdout=True, stderr=True)[:output_max_bytes]
            return ContainerResult(
                exit_code=result.get("StatusCode", -1),
                output=logs.decode("utf-8", errors="replace"),
                duration_seconds=time.monotonic() - start,
            )
        except (ContainerError, ImageNotFound, APIError) as e:
            log.error("container run failed", image=image, error=str(e)[:500])
            return ContainerResult(
                exit_code=-1,
                output="",
                duration_seconds=time.monotonic() - start,
                error=str(e)[:500],
            )
        except Exception as e:
            # docker-py raises ConnectionError/ReadTimeout on wait() timeout
            timed_out = "timeout" in str(e).lower() or "timed out" in str(e).lower()
            log.error("container run error", image=image, timed_out=timed_out, error=str(e)[:500])
            return ContainerResult(
                exit_code=-1,
                output="",
                duration_seconds=time.monotonic() - start,
                timed_out=timed_out,
                error=str(e)[:500],
            )
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception as e:
                    log.warning("container cleanup failed", error=str(e)[:200])

    def ensure_image(self, image: str) -> None:
        try:
            self._client.images.get(image)
        except ImageNotFound:
            log.info("pulling image", image=image)
            self._client.images.pull(image)
