#!/usr/bin/env python3
"""Pre-commit hook: block commits in detached HEAD (e.g. after `git checkout v0.1.0`).

Committing while detached creates commits that belong to no branch —
a divergent history that's easy to lose and hard to merge. This is the
classic `git checkout v0.1.0` trap. Shows the branch-first fix.
"""

import subprocess
import sys

try:  # Windows consoles default to cp1252; force UTF-8 for the ✗/✔ glyphs
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def is_detached() -> bool:
    try:
        ref = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
        ).strip()
    except subprocess.CalledProcessError:
        return False
    return ref == "HEAD"


def main() -> int:
    if not is_detached():
        return 0  # on a branch — normal commit path

    print(
        "\n"
        "❌ Commit in detached HEAD is blocked by the branching guardrail.\n"
        "\n"
        "You are in detached HEAD — usually from `git checkout v0.1.0` (a tag)\n"
        "or `git checkout <commit>`. Committing here creates commits that belong\n"
        "to NO branch: a divergent history that is easy to lose and painful to\n"
        "merge back.\n"
        "\n"
        "The correct ways:\n"
        "  • Patch a frozen release tag (v0.1.0 is immutable):\n"
        "      git switch -c hotfix/v0.1.x v0.1.0   # branch FIRST, then commit\n"
        "      # ... commit + tag v0.1.x ...\n"
        "      # then cherry-pick forward to master\n"
        "  • Just look around at an old version (no changes intended):\n"
        "      git switch master                    # nothing to commit\n"
        "  • Recover a commit you already made here:\n"
        "      git switch -c recover-branch HEAD    # branch at the dangling commit\n"
        "\n"
        "Never commit directly on a detached HEAD.\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
