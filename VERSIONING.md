# Versioning Policy

This project uses **Semantic Versioning** ([semver.org/spec/v2.0.0.html](https://semver.org/spec/v2.0.0.html))
with PEP 440 packaging for Python.

## Version scheme

Versions follow `MAJOR.MINOR.PATCH`:

- **MAJOR** — breaking changes (API, behavior, or data format that users must
  act on).
- **MINOR** — new features, backward compatible.
- **PATCH** — bug fixes, backward compatible.
- Pre-releases use PEP 440 suffixes: `0.2.0a1`, `0.2.0rc1`.

While below `1.0.0`, the `0.x` rule applies: `MINOR` bumps may introduce
breaking changes. This is the standard "pre-stability" convention.

## Release roadmap

| Version | Scope |
|---|---|
| `0.1.0` | **Frozen baseline** — current supervisor + specialist-agent pipeline (Docling extraction, deterministic calculators, whitelisted research, email/Telegram channels, SQLite case store). Tagged and immutable for the hackathon. |
| `0.2.0` | **Agent framework + state management** — migration to a third-party agent framework and richer agent state management. May break internals; the public behavior (channels, verdicts) stays stable. |

## How a release happens

1. **Merge work to `main`.** `main` is always releasable.
2. **Bump the version** in `pyproject.toml` — the single source of truth.
   Never duplicate it in code; read it at runtime via
   `importlib.metadata.version("policy-decoder")`.
3. **Update `CHANGELOG.md`** (Keep a Changelog format): move `[Unreleased]`
   entries into the new version section.
4. **Tag the commit** with an annotated tag: `git tag -a v0.1.0 -m "..."`.
   Lightweight tags are not used for releases.
5. **Publish** — PyPI build for the package, GitHub Release for the tag.

## How the next version is chosen

Version bumps are derived from commits, not picked by hand. The commit
history uses Conventional Commits, so:

| Commit prefix | Version bump |
|---|---|
| `fix:` | PATCH (`0.1.0` → `0.1.1`) |
| `feat:` | MINOR (`0.1.0` → `0.2.0`) |
| `BREAKING CHANGE:` (any prefix) | MAJOR (`0.1.0` → `1.0.0`) |

Tooling such as `python-semantic-release` or `commitizen` can automate steps
2-4 in CI (bump, changelog, tag on push to `main`). Until then, bumps are
done manually following this table.

## Rules

- **One source of truth** for the version: `pyproject.toml`.
- **Every release is tagged.** Tags are how users and tooling find
  reproducible points.
- **Every user-visible change is in the changelog.**
- **`main` is always releasable** — no half-finished work lands on it.
- **The frozen `0.1.0` does not change.** Post-freeze fixes go to `0.1.x`
  only if the hackathon needs them; otherwise they land in `0.2.0`.
