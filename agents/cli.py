"""gitguardian commit — the local-first entry point.

Flow:
  gitguardian commit -m "your message"
    1. fast staged-diff secret scan (warn)
    2. full pipeline: semgrep+gitleaks → classify → fix → test (local agent)
    3. each verified fix lands on its own gitguardian/fix-* branch (+ push + PR via gh)
    4. your staged changes are committed with your message on your branch
    5. unfixable findings block the commit (override with --force)

Also: gitguardian scan — run the pipeline without committing.
"""

import argparse
import asyncio
import sys
import uuid

from langgraph.checkpoint.memory import MemorySaver

from agents.local_graph import build_local_graph
from core.db.models import Scan
from core.db.session import get_session_factory
from core.logging import configure_logging, get_logger
from core.tracing import ScanTracer

log = get_logger("cli")


async def _git(*args: str, cwd: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode().strip(), err.decode().strip()


async def repo_root(cwd: str = ".") -> str:
    rc, out, err = await _git("rev-parse", "--show-toplevel", cwd=cwd)
    if rc != 0:
        print(f"✗ not a git repository ({err[:200]})")
        sys.exit(2)
    return out


async def run_pipeline(
    repo: str, branch: str, message: str, tracer: ScanTracer, scope: str
) -> dict:
    """Run the agent pipeline on the working tree. Returns final state."""
    scan_id = str(uuid.uuid4())

    async with get_session_factory()() as session:
        session.add(Scan(id=uuid.UUID(scan_id), repo_path=repo, branch=branch, status="running"))
        await session.commit()

    graph = build_local_graph(checkpointer=MemorySaver())
    initial = {
        "scan_id": scan_id,
        "repo_path": repo,
        "branch": branch,
        "commit_message": message,
        "scan_scope": scope,
        "findings": [],
        "findings_index": 0,
        "fix_attempts": 0,
        "prs": [],
        "fixed_files": [],
        "events": [],
        "llm_cost_usd": 0.0,
        "llm_input_tokens": 0,
        "llm_output_tokens": 0,
        "trace_url": tracer.url,
    }
    config = {"configurable": {"thread_id": scan_id}, "recursion_limit": 60}
    final = await graph.ainvoke(initial, config=config)
    final["scan_id"] = scan_id
    return final


def _print_findings(findings) -> None:
    for f in findings:
        print(f"  [{f.severity.upper():8s}] {f.rule_id}  {f.file_path}:{f.start_line} ({f.tool})")


async def cmd_commit(args) -> int:
    repo = await repo_root()
    rc, branch, _ = await _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
    rc, staged, _ = await _git("diff", "--cached", "--name-only", cwd=repo)
    if not staged and not args.allow_empty:
        print("✗ nothing staged. `git add` your changes first.")
        return 2

    # Fast staged-diff secret check (advisory — the full scan follows)
    from security.hooks.precommit_scan import scan as fast_scan
    from security.hooks.precommit_scan import staged_diff

    hits = fast_scan(staged_diff())
    if hits:
        print(f"\n⚠ {len(hits)} potential secret(s) in staged changes — full scan follows\n")

    print(f"🛡 GitGuardian scanning {repo} ({branch})…")
    tracer = await ScanTracer.create("gitguardian.commit", {"repo": repo, "branch": branch})
    final = await run_pipeline(repo, branch, args.message, tracer, "staged")

    for event in final.get("events", []):
        await log.ainfo("pipeline", step=event)

    findings = final.get("findings", [])
    prs = final.get("prs", [])

    if not findings:
        print("✓ no security findings")
    else:
        print(f"\n{len(findings)} finding(s):")
        _print_findings(findings)

    for pr in prs:
        if pr.url:
            print(f"  🔀 fix PR: {pr.url}")
        else:
            print(f"  🌿 fix committed on branch: {pr.branch} (push/PR failed — do it manually)")

    unfixable = len(findings) - len(prs)
    if unfixable > 0 and not args.force:
        print(
            f"\n✗ commit blocked: {unfixable} finding(s) could not be fixed automatically.\n"
            "  Fix them manually, or commit anyway with --force"
        )
        return 1

    # Commit the user's staged changes on their branch
    commit_args = ["commit", "-m", args.message]
    if args.allow_empty:
        commit_args.append("--allow-empty")
    rc, out, err = await _git(*commit_args, cwd=repo)
    if rc != 0:
        print(f"✗ git commit failed: {err[:300]}")
        return 1

    cost = final.get("llm_cost_usd", 0.0)
    print(f"\n✓ committed on {branch}: {out.splitlines()[0] if out else ''}")
    print(f"  agent cost: ${cost:.4f}")
    if final.get("trace_url"):
        print(f"  trace: {final['trace_url']}")
    tracer.close()
    return 0


async def cmd_scan(args) -> int:
    repo = await repo_root()
    rc, branch, _ = await _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
    print(f"🛡 GitGuardian scanning {repo} ({branch})…")
    tracer = await ScanTracer.create("gitguardian.scan", {"repo": repo, "branch": branch})
    final = await run_pipeline(repo, branch, "", tracer, "all_changes")
    findings = final.get("findings", [])
    if not findings:
        print("✓ no security findings")
        return 0
    print(f"\n{len(findings)} finding(s):")
    _print_findings(findings)
    for pr in final.get("prs", []):
        print(f"  🔀 {pr.url or pr.branch}")
    if final.get("trace_url"):
        print(f"  trace: {final['trace_url']}")
    tracer.close()
    return 1 if findings and not final.get("prs") else 0


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(prog="gg", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_commit = sub.add_parser("commit", help="scan → fix → then commit")
    p_commit.add_argument("-m", "--message", required=True)
    p_commit.add_argument("--force", action="store_true", help="commit despite unfixable findings")
    p_commit.add_argument("--allow-empty", action="store_true")

    sub.add_parser("scan", help="scan + fix without committing")

    args = parser.parse_args()
    if args.command == "commit":
        sys.exit(asyncio.run(cmd_commit(args)))
    elif args.command == "scan":
        sys.exit(asyncio.run(cmd_scan(args)))


if __name__ == "__main__":
    main()
