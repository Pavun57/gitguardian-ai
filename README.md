# GitGuardian AI — Agentic Security on Every Push

An agentic security system: on every `git push`, it scans for secrets and
vulnerabilities, generates an AI fix, proves it with generated tests in an
isolated container, and opens a pull request for human review.

```
git push → webhook → Semgrep+Gitleaks → classify → Claude fix → pytest in
hardened Docker → branch + PR → check-run → you review & merge
```

**The human is always in the loop** — nothing merges without your approval.
Low-confidence fixes never open PRs.

## Problem

Developers push secrets, vulnerabilities, and misconfigurations to GitHub daily.
Current tools detect issues but don't fix them. GitGuardian AI closes the loop:
**detect → classify → generate fix → test fix → open PR → wait for human approval.**

## Status

**Phase 1 — vertical slice ✅**
- [x] GitHub App webhook receiver (HMAC-verified, deduped, <200ms ACK)
- [x] Semgrep + Gitleaks in hardened sibling containers (custom rules)
- [x] LangGraph agent pipeline (router → scanner → classifier → fix → test → PR)
- [x] Claude fix generation (forced tool-use, full-file rewrite — ADR-0001)
- [x] Generated pytest suites run in network-less, read-only containers (ADR-0002)
- [x] Auto branch + PR with finding table, explanation, test evidence, cost
- [x] Check-runs with inline annotations; BYOK key encryption (Fernet)

**Phase 2 — dashboard + notifications ✅**
- [x] Next.js dashboard: overview, scan history, scan detail, repos, settings
- [x] GitHub OAuth login; BYOK "connect your coding agent" UI
- [x] HITL approval queue — approve (merge) / reject (close) fix PRs
- [x] Slack notifications (encrypted per-installation webhook)

**Phase 3 — pre-commit + evals ✅**
- [x] Pre-commit hook: staged-diff secret scan, blocks criticals (`security/hooks/`)
- [x] Eval harness: dataset + detection-rate/FP metrics — currently **100% detection, 0 FPs** (`evals/`)

**Phase 4 — CI/CD + deployment ✅**
- [x] GitHub Actions CI: lint → test → dogfood scan-evals → dashboard build → docker
- [x] Deploy workflow: GHCR → Azure Container Apps (`docs/architecture/deployment.md`)

## Architecture

See [`docs/architecture/phase1-pipeline.md`](docs/architecture/phase1-pipeline.md)
for the full pipeline diagram, failure semantics, and guardrails. ADRs:
[0001 full-file rewrite](docs/architecture/ADR-0001-full-file-rewrite.md),
[0002 sibling containers](docs/architecture/ADR-0002-sibling-containers.md).

## Setup

### 1. Create the GitHub App

GitHub → Settings → Developer settings → GitHub Apps → New:

| Setting | Value |
|---|---|
| Webhook URL | your smee.io channel URL (dev) |
| Webhook secret | generate one (`openssl rand -hex 20`) |
| Permissions | Contents: RW, Pull requests: RW, Checks: RW, Metadata: R |
| Events | `push`, `installation`, `installation_repositories` |

Download the private key to `secrets/github-app.pem`.

### 2. Configure

```bash
cp .env.example .env
# fill in: GITHUB_APP_ID, GITHUB_WEBHOOK_SECRET, ANTHROPIC_API_KEY,
#          MASTER_ENCRYPTION_KEY (generate: python -c "from cryptography.fernet
#          import Fernet; print(Fernet.generate_key().decode())"),
#          SMEE_CHANNEL_URL
```

### 3. Run

```bash
cd infrastructure/docker
docker compose up -d postgres redis
docker compose --profile tunnel up api worker smee
```

### 4. Install the app on a test repo, push a vulnerability, watch:

- a `gitguardian/scan` check-run appears on the commit,
- findings get inline annotations,
- a `gitguardian/fix-<rule>-<sha>` branch + PR opens with the fix,
  explanation, and passing-test evidence.

## Development

```bash
uv sync
uv run pytest -m "not docker and not e2e"   # fast suite
uv run pytest -m docker                     # real scanner containers
uv run ruff check && uv run ruff format
uv run alembic upgrade head
```

## Guardrails (why this doesn't burn your API key or spam PRs)

- Max 3 findings fixed per push, max 2 fix attempts each
- $0.50/scan LLM budget, checked before every model call
- Low-confidence fixes never open PRs
- The app never scans its own fix branches (loop prevention)

## Safety model

- Webhook HMAC-SHA256 verification; delivery dedup
- LLM-generated code runs only in containers with **no network**, read-only FS,
  non-root user, no capabilities, capped CPU/RAM/PIDs, hard timeouts
- BYOK keys Fernet-encrypted at rest; secrets scrubbed from all logs
- Gitleaks output is redacted before storage — secrets never reach the DB or an LLM prompt
