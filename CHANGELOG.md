# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
See [VERSIONING.md](VERSIONING.md) for the versioning policy.

## [Unreleased]

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
