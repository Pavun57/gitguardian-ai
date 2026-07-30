# GitGuardian AI — Your Agentic Security Guard at Commit Time

**Stop secrets and vulnerabilities before they ever leave your machine.**
GitGuardian runs locally: when you commit, it scans, fixes with *your own*
coding agent (Claude Code / Codex — no API key), proves the fix with tests in
an isolated container, and opens a PR via `gh`. Your code and credentials
never touch a third-party server.

```
gitguardian commit -m "msg"
  → fast staged-diff secret check
  → Semgrep + Gitleaks (hardened containers)
  → classify (fixture-path rules + keep-when-in-doubt LLM filter)
  → your coding agent generates fix + pytest suite
  → tests run in network-less Docker sandbox
  → fix lands on gitguardian/fix-* branch → push → gh pr create
  → your commit proceeds, traced in Langfuse
```

## One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/Pavun57/gitguardian-ai/main/install.sh | bash
```

Then:

```bash
gitguardian start     # dashboard, API, Postgres, Redis, Langfuse
```

Open **http://localhost:3000/settings** → connect your coding agent
(auto-detected — Claude Code or Codex, one click, tested).

## Daily use

```bash
cd your-repo
git add .
gitguardian commit -m "add payment endpoint"
```

- **Clean?** Your commit proceeds immediately.
- **Findings?** The agent fixes them, tests the fixes, and opens fix PRs —
  then your commit proceeds. Unfixable criticals **block** the commit
  (`--force` to override).
- **Just checking?** `gitguardian scan` runs the pipeline without committing.

## The dashboard (localhost:3000)

| Page | What you see |
|---|---|
| Overview | scans, findings, fixes, open PRs, total agent cost |
| Scans | every scan with findings, fix explanations, Langfuse trace links |
| Approvals | HITL queue — approve (merge via `gh`) / reject (close) fix PRs |
| Repos | local repos the pipeline has seen |
| Settings | connect your coding agent, Langfuse keys, Slack |
| Traces ↗ | Langfuse UI (localhost:3100) — every LLM call, tokens, costs |

## Observability — Langfuse (self-hosted)

Every `gitguardian commit` produces a trace: pipeline spans, each LLM
generation (model, tokens, USD cost), per-scan totals. Self-hosted via the
`langfuse` compose profile — traces **stay on your machine** (that's why
Langfuse, not LangSmith). Start with `gitguardian start`, open
http://localhost:3100 (auto-provisioned project `gitguardian-ai`), add the
keys in Settings.

## Commands

```bash
gitguardian commit -m "msg"   # the core flow
gitguardian scan              # scan + fix without committing
gitguardian start|stop|restart|status|logs
gitguardian uninstall         # remove everything cleanly
```

## How it works

| Stage | What happens |
|---|---|
| **Scan** | Semgrep (custom rules) + Gitleaks in hardened sibling containers (no network, read-only, non-root) |
| **Classify** | fixture paths dropped by rule; LLM FP-filter (keep-when-in-doubt); top 3 by severity |
| **Fix** | your agent produces a full-file rewrite + pytest suite; validated by syntax check, single-file diff, and re-scan |
| **Test** | generated tests in an isolated container (no net, read-only FS, caps) — ≤2 retries with failure context |
| **PR** | deterministic `gitguardian/fix-*` branch, pushed with your git auth, PR opened via `gh` |
| **Review** | dashboard approval queue or GitHub — a human always merges |

**Guardrails:** max 3 findings/commit · max 2 fix attempts · $0.50/scan budget ·
low-confidence fixes never ship · unfixable criticals block the commit.

## Development

```bash
git clone https://github.com/Pavun57/gitguardian-ai.git && cd gitguardian-ai
uv sync
docker compose -f infrastructure/docker/docker-compose.yml up -d postgres redis
uv run alembic upgrade head
(cd apps/dashboard && npm install && npm run dev)

uv run pytest -m "not docker"      # unit + graph topology
uv run pytest -m docker            # real scanner containers
uv run python -m evals.metrics.run_eval   # detection eval: 100% / 0 FPs
uv run ruff check
```

## Architecture

- `agents/` — LangGraph pipeline (local) + pluggable agent backends
  (Claude Code, Codex, Anthropic API) + `cli.py` (the `gg` entry point)
- `apps/api` — FastAPI dashboard REST API
- `apps/dashboard` — Next.js dashboard
- `security/` — scanner runners, SARIF/gitleaks parsers, custom rules, pre-commit scanner
- `core/` — config, DB, crypto (Fernet), Langfuse tracing
- `evals/` — vulnerable-sample dataset + detection metrics
- `docs/` — architecture docs and ADRs

## Safety model

- Everything runs on your machine — code never leaves except your normal
  `git push` and the fix PR you review
- LLM-generated code executes only in network-less, read-only, non-root containers
- Credentials (agent tokens, Langfuse keys, Slack) Fernet-encrypted at rest
- Secrets redacted at the parser before they can reach the DB or an LLM prompt
