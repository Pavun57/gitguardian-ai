# GitGuardian AI — Agentic Security on Every Push

An agentic security system: on every `git push`, it scans for secrets and
vulnerabilities, generates an AI fix **with your own coding agent** (Claude Code
or Codex — no API key needed), proves it with generated tests in an isolated
container, and opens a pull request for human review.

```
git push → webhook → Semgrep+Gitleaks → classify → your coding agent fixes →
pytest in hardened Docker → branch + PR → check-run → you review & merge
```

**The human is always in the loop** — nothing merges without your approval.

## One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/Pavun57/gitguardian-ai/main/install.sh | bash
```

The installer checks prerequisites (docker, node 20+, git), clones the repo,
generates secrets, starts Postgres + Redis, installs dependencies, and runs
migrations. When it finishes:

```bash
# 4 terminals from ~/gitguardian-ai:
uv run uvicorn apps.api.main:app --reload --port 8000    # API
uv run arq agents.worker.WorkerSettings                  # agent pipeline
cd apps/dashboard && npm run dev                         # dashboard (localhost:3000)
docker run --rm -it --network host node:22-alpine \
  sh -c "npm install -g smee-client && smee --url https://smee.io/YOUR_CHANNEL --target http://localhost:8000/webhooks/github"
```

Then open **http://localhost:3000/setup** — the wizard:

1. **Creates the GitHub App in one click** (manifest flow: permissions, events,
   webhook URL all pre-filled)
2. Lets you paste the App ID + private key — stored **encrypted** in the DB,
   no `.env` editing
3. **Connect GitHub** → install on your repos (they register automatically)
4. **Connect your coding agent** — auto-detects Claude Code / Codex on your
   machine, tests the connection, done. Fixes bill *your* subscription.

## How it works

| Stage | What happens |
|---|---|
| **Webhook** | HMAC-SHA256 verified, deduped, ACKs <200ms, job queued (arq/Redis) |
| **Scan** | Semgrep (custom rules) + Gitleaks in hardened sibling containers → normalized findings |
| **Classify** | Fixture paths dropped by rule; LLM FP-filter (keep-when-in-doubt); top 3 by severity |
| **Fix** | Your coding agent produces a full-file rewrite + pytest suite (validated: syntax, single-file diff, re-scan) |
| **Test** | Generated tests run in a container with **no network**, read-only FS, non-root, resource caps — ≤2 retries with failure context |
| **PR** | Deterministic branch `gitguardian/fix-<rule>-<sha>`, PR with finding table, explanation, test evidence, cost |
| **Review** | Check-run annotations inline; approve/reject from the dashboard or GitHub |

**Guardrails:** max 3 findings/push · max 2 fix attempts · $0.50/scan budget ·
low-confidence fixes never open PRs · the app never scans its own fix branches.

## Cost tracking

Claude Code reports its real per-call cost (`total_cost_usd`); API-key backends
are priced from token counts. Every scan, fix, and the dashboard totals show
actual spend.

## Dashboard

- **Overview** — scans, findings, fixes, open PRs, total LLM spend
- **Scans** — full history with per-finding detail, fix explanations, PR links
- **Approvals** — the HITL queue: approve (merge) / reject (close) fix PRs
- **Repos** — connected repositories (auto-synced with GitHub)
- **Settings** — connect GitHub, connect your coding agent, Slack webhooks
- **Setup** — GitHub App creation wizard

## Development

```bash
git clone https://github.com/Pavun57/gitguardian-ai.git && cd gitguardian-ai

uv sync                                        # Python deps
docker compose -f infrastructure/docker/docker-compose.yml up -d postgres redis
uv run alembic upgrade head                    # migrations
(cd apps/dashboard && npm install)             # dashboard deps

# run: api / worker / dashboard / smee tunnel (see above)

uv run pytest -m "not docker and not e2e"      # fast suite
uv run pytest -m docker                        # real scanner containers
uv run python -m evals.metrics.run_eval        # detection eval (100%/0 FPs gate)
uv run ruff check && uv run ruff format        # lint
```

## Architecture

- `apps/api` — FastAPI webhook receiver + dashboard REST API
- `apps/dashboard` — Next.js dashboard
- `agents/` — LangGraph pipeline (router → scanner → classifier → fix → test → PR → notify) + pluggable agent backends (Claude Code, Codex, Anthropic API)
- `security/` — scanner runners (hardened containers), SARIF/gitleaks parsers, custom Semgrep rules, pre-commit hook
- `core/` — config, DB models, crypto (Fernet), runtime app-config
- `evals/` — vulnerable-sample dataset + detection metrics
- `docs/architecture/` — pipeline doc, ADRs ([full-file rewrite](docs/architecture/ADR-0001-full-file-rewrite.md), [sibling containers](docs/architecture/ADR-0002-sibling-containers.md)), [deployment](docs/architecture/deployment.md)

## Safety model

- Webhook HMAC-SHA256 verification + delivery dedup
- LLM-generated code executes only in network-less, read-only, non-root containers
- Credentials (GitHub key, agent tokens, Slack webhooks) Fernet-encrypted at rest
- Secrets scrubbed from logs; gitleaks output redacted before it can reach the DB or a prompt
