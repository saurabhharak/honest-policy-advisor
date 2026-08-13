# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
See [VERSIONING.md](VERSIONING.md) for the versioning policy.

## [Unreleased]

### Added

- LangGraph pipeline (opt-in via `LANGGRAPH_ENABLED`): compiled graph with
  route/extract/analyst/text nodes, parallel extract ∥ research fan-out,
  and a text intent flow replacing the legacy CaseState machine.
- Per-product gold-standard rubrics (`data/rubrics/`) with dual-track
  page-by-page triage: parallel per-page rubric review + a global table
  analyzer, targeted re-read for missing fields, and a layman-writer
  verdict node.
- L0-L3 layered memory over LangGraph's MemoryStore (raw → atoms →
  scenarios → persona) with a stable `user_id` spanning email + Telegram;
  Postgres + pgvector backends (`graph/backends.py`).
- Opik evaluation harness (`evals/`): gold datasets + deterministic metrics
  for all six agents, plus a robust LLM judge (`--live`) that tolerates
  Featherless reasoning-mode output.
- `scripts/seed_evals.py` (Docling cache + dataset seeding),
  `scripts/live_test_graph.py`, `scripts/trigger_policy_flow.py`.

### Fixed

- LLM responses on Featherless reasoning models returned content in
  `message.reasoning` with `content` empty — every LLM call site now reads
  via `response_text()` (content → reasoning fallback), fixing empty
  extraction/analysis/letters.
- `GraphRuntime.start()` discarded `_build_graph()`'s return value, so
  `graph` stayed `None` and messages silently fell back to the legacy
  supervisor; the built graph/user_store/agent_context/backends are now
  captured (regression test in `tests/test_main_runtime.py`).
- Family-floater premium extraction: `annual_premium` is now
  table-authoritative in `accumulate`, so the whole-table premium (both
  insured persons) overrides a page-local partial row.
- Replaced leftover debug `print()` in the extractor with structured
  logging.
- CI tests now run without secrets: `tests/conftest.py` provides dummy env
  vars and resets the config cache so the suite passes in clean CI runners.
- CI bandit step emits real SARIF via the `bandit-sarif-formatter` plugin
  (bandit 1.9.x dropped the built-in sarif formatter).
- CI enforces the branching policy server-side (see BRANCHING.md): blocks
  direct pushes to `master` and requires a `CHANGELOG.md` entry for `src/`
  changes.

## [0.1.0] - 2026-08-09

### Added

- Multi-agent pipeline: supervisor + specialist agents (router, extractor,
  researcher, health analyst, life analyst, letter drafter).
- Docling PDF parsing (layout + TableFormer + OCR) with chunked/routed
  extraction and short-circuit when data is genuinely absent from the document.
- Deterministic financial calculators: XIRR, term + SIP alternative,
  surrender loss, opportunity cost, health policy scoring.
- IRDAI FY2024-25 insurer benchmark dataset and lookups.
- Live research from whitelisted domains (`irdai.gov.in`, `joinditto.in`,
  `beshak.org`).
- Email + Telegram channels through a single `on_message` handler (Caspian SDK).
- SQLite persistence via `case_manager` + `store`.
- NeMo guardrails (opt-in), Opik tracing (opt-in), structured logging.
- Gitleaks / Bandit / Trivy security scanning in CI.

### Fixed

- Telegram file attachments delivered as `api.telegram.orgfile/bot<token>/...`
  (missing slash) are now downloaded as PDFs regardless of suffix, and the
  malformed URL is normalized before fetching.
- Researcher no longer hangs: replaced the per-fetch `uvx mcp-server-fetch`
  stdio subprocess (which could stall indefinitely on `session.initialize()`)
  with a bounded HTTP fetch against whitelisted domains.
- Docling no longer OOMs on long policies: layout/OCR/table stages batch one
  page at a time with capped queues instead of 4-page batches that triggered
  `std::bad_alloc` on 20+ page documents.
- Router classifies local PDF files via Docling markdown keywords instead of
  requiring a remote URL.

## [0.1.0-rc.1] - 2026-08-08

- Pre-release cut of the current architecture ahead of the hackathon freeze.
