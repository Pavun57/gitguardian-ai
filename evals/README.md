# Evals (Phase 3 skeleton)

Phase 1 ships the pipeline; Phase 3 proves it. Planned structure:

## Datasets (`datasets/`)
- 50 deliberately vulnerable code samples across categories:
  hardcoded secrets, injection (SQL/command/code), insecure deserialization,
  weak crypto, path traversal, misconfiguration.
- Sources: hand-written, OWASP benchmark, Juliet test cases (Python subset).

## Metrics (`metrics/`)
- **Detection rate** — findings the scanner+classifier surfaces / known vulns.
- **Fix validity** — re-scan clean + generated tests pass.
- **Fix correctness** (sampled, human-reviewed) — does the fix remove the vuln
  without changing behavior?
- **FP rate** — FP filter precision/recall against labeled samples.
- **Cost per fix** — mean/p95 LLM spend per merged PR.
- **Time to PR** — webhook receipt → PR opened.

## Benchmarks (`benchmarks/`)
- Full pipeline runs against the dataset in CI (nightly): every sample pushed
  to a scratch repo, pipeline output scored automatically.
- Regression gate: fix-validity and detection-rate must not drop >5% between
  releases.

## Why this matters
"Tests pass" is evidence, not proof. The eval harness is the answer to the
hardest question about this system: *how often is the fix actually right?*
