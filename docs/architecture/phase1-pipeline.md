# Phase 1 Pipeline

```
git push
  │
  ▼
GitHub webhook ──► POST /webhooks/github (FastAPI)
                     1. HMAC-SHA256 signature verification (raw body)
                     2. delivery-id dedup (Redis, 24h)
                     3. INSERT scan (status=queued) → enqueue arq job → 202
                     ACK budget: <200ms. No scanning in the request handler.
  │
  ▼
arq worker ──► LangGraph (thread_id = scan_id)
  │
  ├─ router      skip bot pushes / gitguardian/* branches (loop prevention),
  │              shallow-clone via installation token (header auth, never in
  │              .git/config), checkout pushed commit
  ├─ scanner     Semgrep (custom rules, SARIF) + Gitleaks (filesystem mode)
  │              in parallel hardened containers → normalized Findings → DB
  ├─ classifier  severity sort → haiku FP-filter (best-effort; rule-based
  │              fallback) → top MAX_FINDINGS_PER_SCAN (3)
  ├─ fix loop (per finding, ≤2 attempts)
  │    fix_generate  Claude (forced tool-use): full-file rewrite + pytest
  │    fix_apply     path assert → syntax check → single-file diff → re-scan
  │    test_run      pytest in hardened container (no net, read-only, non-root)
  │    fail → retry with pytest output as context
  ├─ pr_create   deterministic branch gitguardian/fix-{rule}-{sha7},
  │              bot-authored commit, PR with finding table + test evidence
  └─ notify      check-run conclusion + annotations on the commit
```

## Failure semantics

| Node | Failure | Behavior |
|---|---|---|
| scanner | tool crash | other tool continues; scan completes with partial results |
| classifier | LLM error | rule-based severity only, pipeline continues |
| fix_generate | malformed output / low confidence | retry 3x / route to human, no PR |
| fix_apply | validation rejects | counts as attempt; retry with validator feedback |
| test_run | tests fail | retry ≤2 with pytest output; then human, no PR |
| pr_create | GitHub 5xx/429 | tenacity backoff 3x |
| notify | any | logged and swallowed — never fails the scan |

## Guardrails

- `MAX_FINDINGS_PER_SCAN=3` — no PR spam
- `MAX_FIX_ATTEMPTS=2` — bounded agentic loop
- `SCAN_BUDGET_USD=0.50` — checked before every LLM call
- Files >1500 lines → human review (full-file rewrite constraint)
- Bot pushes and `gitguardian/*` branches are never scanned (loop prevention)

## HITL

The PR is the approval gate. Low-confidence fixes, budget exhaustion, and
repeatedly-failing fixes produce a neutral check-run and no PR — a human takes
over. The dashboard approval queue arrives in Phase 2.
