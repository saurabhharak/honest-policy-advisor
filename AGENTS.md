# Policy Decoder → honest-policy-advisor

AI agent that gives an honest second opinion on health and life insurance: reads the policy document (PDF/photo), tells you if you were mis-sold, flags what's alarming or worth changing, and drafts the complaint letter to get your money back. Works for policies you own AND policies you're planning to buy.

## Hackathon

Caspian AI Agent Hackathon (15-day, online). Agent must use caspian-sdk and run on 2+ channels through a single on_message handler.

## What we're building

The agent receives an insurance policy PDF via email attachment or Telegram photo. A **supervisor + specialist agents** pipeline processes it:

- **Router Agent** — classifies the document (HEALTH/LIFE/TERM)
- **Extractor Agent** — Docling parses the PDF (layout + tables + OCR), then text/table LLMs extract the fields; **short-circuits** when data is genuinely absent (e.g. user uploaded a receipt, not the full policy)
- **Researcher Agent** — fetches live market/regulatory context from whitelisted domains (`irdai.gov.in`, `joinditto.in`, `beshak.org`)
- **Health Analyst / Life Analyst** — write the honest verdict from **deterministic Python calculations** (never LLM math)
- **Letter Drafter** — free-look / complaint / ombudsman letters

The verdict must be honest — including "this policy is fine" when it is.

Channels: email (formal, PDF attachments, complaint letters) + Telegram (quick questions, photo uploads). Both hit the same `on_message` handler — no channel branching.

## Project structure

```
policy-decoder/
├── src/policydecoder/           # the package
│   ├── main.py                  # entry point, wires channels + supervisor/graph
│   ├── handler.py               # one on_message handler
│   ├── supervisor.py            # legacy async orchestrator (flag-off fallback)
│   ├── graph/                   # LangGraph pipeline (LANGGRAPH_ENABLED)
│   │   ├── pipeline.py          # build_graph: nodes, edges, memory chain
│   │   ├── nodes.py             # route/extract/analyst/text node functions
│   │   ├── memory.py            # L0-L3 layered memory over MemoryStore
│   │   ├── identity.py          # UserStore: stable user_id (email + Telegram)
│   │   ├── backends.py          # Postgres pool + checkpointer/store setup
│   │   ├── triage.py            # dual-track page-by-page triage + layman writer
│   │   ├── rubrics.py           # per-product gold-standard rubrics + prompt builders
│   │   ├── prompt_store.py      # rubric/prompt storage in PostgresStore namespaces
│   │   └── state.py             # PipelineState + GraphContext
│   ├── embeddings.py            # OpenAI embeddings wrapper for semantic search
│   ├── agents/                  # specialist agents
│   │   ├── extractor_agent.py   # Docling + text/table extraction + short-circuit
│   │   ├── researcher_agent.py  # whitelisted fetch + LLM summary
│   │   ├── health_analyst.py    # health verdict (calls health_calculator)
│   │   ├── life_analyst.py      # life verdict (calls calculator)
│   │   ├── letter_drafter.py    # letters
│   │   └── base.py              # shared LLM executor + tracing
│   ├── docling_parser.py        # PDF → markdown/tables (per-parse lifecycle)
│   ├── extractor.py             # vision-model extraction (photo path + fallback)
│   ├── calculator.py            # pure Python life financial math
│   ├── health_calculator.py     # pure Python health scoring
│   ├── analyzer.py              # shared LLM prompt executor + draft methods
│   ├── router.py                # document classifier
│   ├── schemas.py               # Pydantic extraction schemas
│   ├── insurer_data.py          # IRDAI benchmark loader
│   ├── case_manager.py          # state machine
│   ├── store.py                 # SQLite persistence
│   ├── guardrails.py / guardrails_config.py  # NeMo safety rails
│   ├── opik_tracing.py / logging.py          # observability
│   ├── email_link.py            # Gmail compose links
│   ├── prompts.py               # prompt templates
│   ├── config.py                # env config
│   └── data/insurer_metrics.json  # IRDAI FY24-25 benchmark dataset
├── tests/
├── scripts/                     # download/generate test policies, run_policy_file
├── PLAN.md
├── ENGINEERING.md
├── HACKATHON.md
└── AGENTS.md                    # this file
```

## Key rules

- **LLM never does math.** `calculator.py` / `health_calculator.py` handle all financial computation.
- **LLM never sends messages.** `handler.py` replies via `message.reply()`.
- **Tests first.** `uv run pytest` before any commit. Tests never hit real LLM/channels/timers.
- **No channel branching.** `message.reply()` routes automatically.
- **Short-circuit extraction.** Never burn retries confirming data isn't in the document.
- **Docling is per-parse, never a singleton** (GPU memory).
- **Researcher cites only whitelisted domains** (fact-drift prevention).
- **Guardrails/Opik/Docling are opt-in** via env vars; disabled = zero latency.
- **LangGraph is opt-in** (`LANGGRAPH_ENABLED`); requires Postgres + pgvector (`POSTGRES_DSN`). Async backends on one persistent event loop; never a per-message `asyncio.run` once the pool exists.
- **Memory is layered L0-L3** namespaced per stable `user_id`; `merge_l3` only runs after `extract_l1` produced new atoms.
- **Rubrics are per-product gold-standard checklists** (`data/rubrics/`) stored in the store; `use_rubric_triage` routes media through the dual-track page triage (text pages ∥ global table analyzer). LLM notices/explains; calculators do all math.
- **Quality gates:** `ruff check`, `ruff format --check`, `mypy`, `pytest` — all in CI.

## SDK reference

Live integration guide: https://api.trycaspianai.com/SKILL.md
SDK repo: https://github.com/TryCaspian/caspian-sdk

Note: the SDK is channel/messaging only — it has **no agent-state API**. State lives in our `case_manager.py` + SQLite `store.py` (legacy) or LangGraph checkpointer + MemoryStore (when `LANGGRAPH_ENABLED`).
