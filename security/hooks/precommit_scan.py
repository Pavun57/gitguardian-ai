"""Pre-commit secret scanner — fast, local, offline.

Runs against the *staged diff* only (what's about to be committed), applies a
compact set of high-precision secret patterns, and blocks the commit on any
match. This is the <2s first line of defense; the server-side pipeline is the
enforcement layer. Bypass: `git commit --no-verify` (server still catches it).

Exit codes: 0 = clean, 1 = secrets found (commit blocked), 2 = usage error.
"""

import re
import subprocess
import sys

# High-precision patterns only — a pre-commit hook must not false-positive
# on normal code. Each: (name, compiled regex, severity)
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("AWS access key", re.compile(r"(?:AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("GitHub fine-grained PAT", re.compile(r"github_pat_[A-Za-z0-9_]{82,}")),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9\-_]{40,}")),
    ("OpenAI API key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9\-_]{40,}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z\-_]{35}")),
    ("Stripe secret key", re.compile(r"[sr]k_live_[0-9A-Za-z]{20,}")),
    (
        "Generic assignment",
        re.compile(r"(?i)(?:password|passwd|secret|api[_-]?key)\s*=\s*['\"][^'\"\s]{16,}['\"]"),
    ),
]

# Obvious placeholders that should NOT block a commit
ALLOWLIST = re.compile(
    r"(?i)(example|placeholder|dummy|fake|test|changeme|your[_-]?key|xxxx|<[a-z_]+>|\*{4,})"
)


def staged_diff() -> str:
    """Added lines of the staged diff, with file context."""
    out = subprocess.run(
        ["git", "diff", "--cached", "--unified=0", "--diff-filter=ACMR"],  # noqa: S607
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        print("gitguardian: cannot read staged diff", file=sys.stderr)
        sys.exit(2)
    return out.stdout


def scan(diff: str) -> list[tuple[str, str, str]]:
    """Return (file, pattern_name, line_preview) for each hit."""
    hits = []
    current_file = "?"
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        content = line[1:]
        for name, pattern in PATTERNS:
            if pattern.search(content) and not ALLOWLIST.search(content):
                hits.append((current_file, name, content.strip()[:80]))
    return hits


def main() -> int:
    hits = scan(staged_diff())
    if not hits:
        return 0

    print("\n🛡 GitGuardian pre-commit: potential secrets detected\n")
    for file, name, preview in hits:
        print(f"  ✗ {file}: {name}")
        print(f"      {preview}\n")
    print("Commit blocked. Remove the secret or use an env var / secrets manager.")
    print("To bypass (server-side scan still runs): git commit --no-verify\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
