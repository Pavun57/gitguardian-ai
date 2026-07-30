"""Eval runner — detection rate and false-positive rate against the dataset.

Runs the real scanners (Docker containers) over each dataset sample and scores
whether the expected rules fire. Fix-validity eval (running the full agent
loop per sample) layers on top with --fix once the API key is configured.

Usage:
  uv run python -m evals.metrics.run_eval            # detection + FP rate
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from agents.scanner.node import run_scanners

DATASET = Path(__file__).resolve().parent.parent / "datasets"


async def evaluate_sample(sample: dict) -> dict:
    src = DATASET / "vulnerable" / sample["file"]
    workdir = tempfile.mkdtemp(prefix="gg-eval-")
    target = Path(workdir) / sample["file"]
    target.write_text(src.read_text())

    findings = await run_scanners(workdir)
    fired_rules = {f.rule_id for f in findings}
    fired_tools = {f.tool for f in findings}

    expected = set(sample["expected_rules"])
    detected = expected <= fired_rules
    # FP: findings on a sample that expects none, or rules outside expected set
    unexpected = fired_rules - expected if expected else fired_rules

    import shutil

    shutil.rmtree(workdir, ignore_errors=True)
    return {
        "file": sample["file"],
        "category": sample["category"],
        "detected": detected,
        "expected": sorted(expected),
        "fired": sorted(fired_rules),
        "false_positives": sorted(unexpected) if sample["category"] == "clean" else [],
        "tools": sorted(fired_tools),
    }


async def main() -> int:
    manifest = json.loads((DATASET / "manifest.json").read_text())
    results = await asyncio.gather(*[evaluate_sample(s) for s in manifest])

    vuln = [r for r in results if r["category"] != "clean"]
    clean = [r for r in results if r["category"] == "clean"]

    detection_rate = sum(r["detected"] for r in vuln) / max(len(vuln), 1)
    fp_total = sum(len(r["false_positives"]) for r in clean)

    print("\n=== GitGuardian eval — detection ===")
    for r in results:
        mark = "✅" if r["detected"] else "❌"
        print(f"{mark} {r['file']:24s} {r['category']:24s} fired={r['fired']}")

    print(
        f"\nDetection rate: {detection_rate:.0%} ({sum(r['detected'] for r in vuln)}/{len(vuln)})"
    )
    print(f"False positives on clean samples: {fp_total}")

    report = {"detection_rate": detection_rate, "false_positives": fp_total, "results": results}
    out = DATASET.parent / "metrics" / "last_run.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"Report written to {out}")

    return 0 if detection_rate == 1.0 and fp_total == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
