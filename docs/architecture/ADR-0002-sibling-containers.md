# ADR-0002: Sibling containers for untrusted workloads

**Status:** Accepted (Phase 1)

## Context

Two kinds of untrusted work run inside GitGuardian:

1. **Scanners** (Semgrep/Gitleaks) executing over arbitrary pushed code.
2. **LLM-generated pytest suites** — model output is untrusted by definition;
   a prompt-injected or buggy test could attempt network exfiltration or
   resource exhaustion.

Options: Docker-in-Docker (DinD), sibling containers via the mounted Docker
socket, or a micro-VM runtime (gVisor/Firecracker).

## Decision

Sibling containers. The `worker` container mounts `/var/run/docker.sock` and
spawns hardened siblings:

```
--network none            no exfiltration, no package downloads
--memory 512m --cpus 1    resource caps
--pids-limit 128          fork-bomb guard
--read-only + tmpfs /tmp  immutable root FS
--user 1000:1000          non-root
--cap-drop ALL            no capabilities
no-new-privileges         no setuid escalation
workspace mounted :ro     live clone is never writable from inside
hard wall-clock timeout   container always killed + removed
```

## Trade-offs

- **Accepted risk:** the mounted socket makes the worker host-root-equivalent.
  A worker compromise is a host compromise. For a single-tenant portfolio/dev
  deployment this is acceptable; it is NOT acceptable for multi-tenant SaaS.
- **Production path:** run test workloads under gVisor (`--runtime=runsc`) or
  Firecracker, and drop the socket in favor of a dedicated runner pool.
- **Known limitation:** `--network none` means generated tests can't
  `pip install`. The test prompt requires stdlib-only tests that exercise the
  fixed function in isolation — which also makes tests faster and less flaky.
