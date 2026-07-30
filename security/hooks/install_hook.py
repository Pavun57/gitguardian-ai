#!/usr/bin/env python3
"""Install the GitGuardian pre-commit hook into a repository.

Usage: uv run python security/hooks/install_hook.py /path/to/repo
Writes .git/hooks/pre-commit, pointing at this scanner. Non-destructive:
an existing hook is backed up to pre-commit.backup-<timestamp>.
"""

import shutil
import stat
import sys
import time
from pathlib import Path

SCANNER = Path(__file__).resolve().parent / "precommit_scan.py"

HOOK = f"""#!/bin/sh
# GitGuardian AI pre-commit hook — staged-diff secret scan.
# Bypass: git commit --no-verify (server-side pipeline still scans on push).
python3 "{SCANNER}" || exit 1
"""


def install(repo_path: str) -> None:
    git_dir = Path(repo_path) / ".git"
    if not git_dir.exists():
        print(f"not a git repo: {repo_path}", file=sys.stderr)
        sys.exit(2)

    hook = git_dir / "hooks" / "pre-commit"
    if hook.exists():
        backup = hook.with_suffix(f".backup-{int(time.time())}")
        shutil.copy2(hook, backup)
        print(f"existing hook backed up to {backup}")

    hook.write_text(HOOK)
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"✓ pre-commit hook installed in {repo_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    install(sys.argv[1])
