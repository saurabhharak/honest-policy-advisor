#!/usr/bin/env python3
"""Pre-commit hook: block direct commits to master.

Shows the correct GitHub Flow way instead of silently passing.
Exit 1 blocks the commit with guidance; --fix auto-creates the branch.
"""

import subprocess
import sys

try:  # Windows consoles default to cp1252; force UTF-8 for the ✗/✔ glyphs
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def current_branch() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
        ).strip()
    except subprocess.CalledProcessError:
        return ""


def main() -> int:
    branch = current_branch()
    if branch != "master":
        return 0  # only master is guarded

    if "--fix" in sys.argv:
        subprocess.run(["git", "checkout", "-b", "fix/guardrail-auto"], check=False)
        print("✔ Created fix/guardrail-auto and switched to it. Commit here.")
        return 1  # still block: re-run commit on the new branch

    print(
        "\n"
        "❌ Direct commit to 'master' is blocked by the branching guardrail.\n"
        "\n"
        "This project uses GitHub Flow (see BRANCHING.md):\n"
        "  • master is the integration branch — always releasable, never committed to directly\n"
        "  • every change lands via a short-lived branch merged in a PR\n"
        "\n"
        "The correct way:\n"
        "  git checkout -b feat/my-change     # or fix/my-change, docs/my-change\n"
        "  git add <files>\n"
        "  git commit\n"
        "  git push -u origin feat/my-change  # then open a PR to master\n"
        "\n"
        "If this is an emergency hotfix against a frozen release tag:\n"
        "  git checkout -b hotfix/v0.1.x v0.1.0   # isolate on the tag\n"
        "  # commit, tag, then cherry-pick forward to master\n"
        "\n"
        "To auto-create a branch and re-run the commit:  git commit --no-verify "
        "(not recommended) or switch branches first.\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
