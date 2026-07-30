# ADR-0001: Full-file rewrite instead of unified diffs for AI fixes

**Status:** Accepted (Phase 1)

## Context

The fix agent must apply model output to a checked-out repo. Two options:

1. **Unified diff** — model emits a patch, we apply with `git apply`.
2. **Full-file rewrite** — model emits the complete corrected file, we overwrite.

Diff application failure is the top flakiness source in coding agents: context-line
drift, whitespace/CRLF differences, and partially-applied hunks all produce silent or
loud corruption. Full-file rewrite is trivially, deterministically applicable.

## Decision

Full-file rewrite, enforced through forced tool-use structured output
(`submit_fix` tool with a `fixed_file_content` field). Files over
`MAX_FILE_LINES` (1500) are rejected and routed to human review — secret/vuln
findings are almost always in small config or source files.

## Consequences

- Higher output-token cost per fix; bounded by MAX_FINDINGS_PER_SCAN=3 and the
  per-scan dollar budget.
- Validation is simple and strong: syntax check → single-file git-diff assertion →
  re-scan (original rule must no longer fire; no new ≥-severity findings).
- The model also emits the pytest suite in the same call, keeping fix and tests
  coherent.
