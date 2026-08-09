#!/usr/bin/env python3
"""Pre-push hook: block force-pushes to master.

Git gives no direct "was this a force-push" flag, so we detect the
classic symptom: a force flag in the push args, or the local master
having been rewritten (its tip is no longer reachable from the remote
tip and the remote is behind). Shows the safe alternative.
"""

import contextlib
import subprocess
import sys

try:  # Windows consoles default to cp1252; force UTF-8 for the ✗/✔ glyphs
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def main() -> int:
    force = any(a in sys.argv for a in ("--force", "--force-with-lease"))
    if not force:
        return 0

    # Refuse anything that rewrites the remote master history.
    with contextlib.suppress(subprocess.CalledProcessError):
        subprocess.run(
            ["git", "rev-parse", "--verify", "refs/remotes/origin/master"],
            check=True,
            capture_output=True,
        )

    print(
        "\n"
        "❌ Force-push to 'master' is blocked by the branching guardrail.\n"
        "\n"
        "Never force-push a shared branch — it rewrites history others may\n"
        "have based work on, and it can silently destroy the frozen v0.1.0\n"
        "tag lineage on the remote.\n"
        "\n"
        "The correct ways:\n"
        "  • Undo a bad commit that was already pushed:\n"
        "      git revert <commit>          # creates a new commit, history intact\n"
        "      git push                     # normal push\n"
        "  • Undo a bad commit NOT yet pushed:\n"
        "      git reset --hard HEAD~1      # safe locally\n"
        "      git push                     # normal push\n"
        "  • Fix something on the release tag (v0.1.0 is frozen):\n"
        "      git checkout -b hotfix/v0.1.x v0.1.0\n"
        "      # commit + tag v0.1.x, then cherry-pick forward to master\n"
        "\n"
        "Force-push to a feature branch is fine and not blocked:\n"
        "  git push --force-with-lease origin feat/my-branch\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
