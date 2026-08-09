# Branching Strategy

This project uses **GitHub Flow** (trunk-based): one long-lived integration
branch with short-lived feature branches merged via pull requests. Releases
are **tags on `master`**, not branches.

## Model

```
        v0.1.0 (tag)          v0.2.0 (tag)
            │                      │
            ▼                      ▼
master ─────●──────────────────────●──────────────▶  always releasable
            ▲                      ▲
            │                      │
    ┌───────┴────────┐     ┌───────┴────────┐
    │ feat/…         │     │ feat/agent-    │
    │ fix/…          │     │ framework      │
    │ docs/…         │     │ feat/state-mgmt│
    └────────────────┘     └────────────────┘
        short-lived PR branches, deleted after merge
```

## Branch rules

| Branch | Lifetime | Purpose |
|---|---|---|
| `master` | Permanent | The only integration branch. Always releasable. Never commit to it directly. |
| `feat/<name>` | Short-lived | New features. Merge to `master` via PR. |
| `fix/<name>` | Short-lived | Bug fixes. Merge to `master` via PR. |
| `hotfix/v<ver>` | Short-lived | Isolated fixes against a **frozen release tag** (e.g. `v0.1.1` off `v0.1.0`). Merged via PR or cherry-picked back. |
| `docs/`, `chore/`, `ci/` | Short-lived | Non-code changes, same PR flow. |

There is **no `develop` branch**. Trunk-based flow keeps one integration
line; releases are tags, so a separate integration branch adds overhead
without benefit for this project.

## Releases are tags, not branches

A version never "overrides" previous work:

- `v0.1.0` is a **permanent, immutable pointer** to commit `04f362f`.
- Future work on `master` creates **new commits on top** of it — the tagged
  snapshot never changes.
- To work on a frozen release (e.g. an emergency fix for v0.1.0 while
  v0.2.0 is in progress):
  ```bash
  git checkout -b hotfix/v0.1.1 v0.1.0   # isolate on the old code
  # ... fix + commit ...
  git tag -a v0.1.1 -m "emergency fix for v0.1.0"
  git checkout master
  git cherry-pick <fix-commit>           # bring the fix forward, never overwrite
  ```
- The versioning policy (see [VERSIONING.md](VERSIONING.md)) decides whether
  a fix ships as `0.1.x` or rides into `0.2.0`.

## The one rule that makes this work

**`master` is always releasable.** Any commit on `master` could be tagged
and shipped. Concretely:

- No work-in-progress on `master` — half-finished features live on branches.
- No merge that breaks the build/tests/demo.
- No direct commits to `master` — every change arrives via a merged PR or a
  cherry-pick with a reason.

## Guardrails (automated enforcement)

Git hooks installed via pre-commit enforce the model and show the correct
fix when someone does the wrong thing:

| Mistake | Hook | What it tells you |
|---|---|---|
| Committing directly to `master` | `pre-commit` → `no-commit-on-master` | Create a `feat/…`/`fix/…` branch and commit there. |
| Force-pushing `master` (history rewrite) | `pre-push` → `no-force-push-master` | Never force-push shared branches; use `git revert` instead. |

Install with:

```bash
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```
