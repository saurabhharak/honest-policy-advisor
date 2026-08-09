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
| Committing in detached HEAD (e.g. after `git checkout v0.1.0`) | `pre-commit` → `no-commit-on-detached-head` | `git switch -c hotfix/v0.1.x v0.1.0` first — never commit on a tag. |
| Force-pushing `master` (history rewrite) | `pre-push` → `no-force-push-master` | Never force-push shared branches; use `git revert` instead. |

### Limitations (honest list)

Pre-commit hooks are **local and advisory**:

- They only run for people who installed them
  (`uv run pre-commit install --hook-type pre-commit --hook-type pre-push`).
- `git commit --no-verify` bypasses them.
- A tag's own tree predates the hooks — checking out `v0.1.0` and committing
  there won't find the hook files in that tree. The detached-HEAD hook only
  protects you when your *working tree* has it (i.e. you checked out a branch
  that contains it).

### Server-side enforcement (the actual system check)

The local hooks are the first line; the **CI workflow
(`.github/workflows/ci.yml` → `git-guardrails` job)** is the enforcement that
cannot be bypassed locally. On every push to `master` and every PR it checks:

| Check | Fails when |
|---|---|
| Direct push to `master` | Someone pushes straight to `master` instead of a PR |
| Changelog updated | A `src/` change (non-doc) lands without a `CHANGELOG.md` entry |
| Tag immutability | `v0.1.0` (or any release tag) is moved/rewritten |

It runs the same rules the local hooks enforce, but on the server — so
`--no-verify` doesn't matter. A violating PR is red and cannot merge.

### The hard layer: remote branch rules

For a shared repo, the *hardest* enforcement is configured on the git host
(GitHub "branch protection", GitLab "protected branches", etc.) and cannot be
overridden by anyone without admin rights:

- **Protect `master`**: no direct pushes, only PRs with required review + CI.
- **Disable force-push** on `master` (the rewrite that could orphan history).
- **Require status checks** — the `git-guardrails` job must be green.
- **Protect the `v0.1.0` tag** — GitHub "Rulesets" can make a tag read-only so
  it can't be deleted or moved, even by maintainers.

The three layers — local hooks (advice), CI (enforcement), branch rules
(hard protection) — are the standard defense-in-depth for this policy.

Install with:

```bash
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```
