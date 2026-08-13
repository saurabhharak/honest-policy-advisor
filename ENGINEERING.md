# Engineering rules for honest-policy-advisor

These are the rules every line of code in this project follows. They exist because we've seen what breaks during a demo — and what breaks in production.

## The agent harness pattern

The LLM proposes. The harness executes. This is the most important rule in the project.

The LLM reads a policy and says "this looks like a ULIP with a 4% premium allocation charge." The harness takes that finding and decides what to do with it. The LLM never sends a message, never calls an API, never writes to the database.

```
BAD:  LLM → calls send_email() → email sent
GOOD: LLM → "this is mis-sold, draft a complaint" → harness validates → harness sends → harness logs
```

## The LLM never does math

XIRR, compound interest, surrender value, SIP projections, room-rent-cap flags. None of this touches the LLM. All of it lives in `calculator.py` / `health_calculator.py` as pure Python functions.

Why: LLMs hallucinate numbers. A hallucinated surrender value that's 10% too high is terrible financial advice. A Python function with the same inputs gives the same output every time.

```
BAD:  "The LLM calculated your XIRR as 3.8%"
GOOD: calculator.xirr(cash_flows) → 0.038 → passed to LLM for the report
```

## Single responsibility per module

| Module | Its one job | What it does NOT do |
|---|---|---|
| `handler.py` | Route messages; materialize attachments | Analyze, calculate, draft letters |
| `supervisor.py` | Legacy orchestrator (flag-off fallback) | Do math, generate content |
| `graph/pipeline.py` | Build the compiled LangGraph (nodes, edges, memory chain) | Do math, generate content |
| `graph/nodes.py` | Graph node functions (route, extract, analyst, text flow) | Do math, draft letters |
| `graph/memory.py` | L0-L3 layered memory over MemoryStore | Generate content, send messages |
| `graph/identity.py` | UserStore: stable user_id across email + Telegram | Anything else |
| `graph/backends.py` | Postgres pool + checkpointer/store setup + teardown | Business logic |
| `agents/extractor_agent.py` | Parse + extract fields; short-circuit on missing data | Analyze, draft letters |
| `agents/researcher_agent.py` | Fetch whitelisted sources; summarize | Compute policy numbers |
| `agents/health_analyst.py` / `life_analyst.py` | Write honest verdict from computed data | Do math |
| `agents/letter_drafter.py` | Draft letters | Analyze |
| `docling_parser.py` | PDF → markdown/tables (per-parse lifecycle) | Anything else |
| `calculator.py` / `health_calculator.py` | Pure financial math (incl. shared `life_calc`) | LLM calls, state |
| `case_manager.py` / `store.py` | Legacy SQLite state machine (flag-off fallback) | Send messages, call LLM |
| `guardrails.py` | Input/output safety rails | Anything else |
| `evals/` | Opik evaluation harness (datasets, tasks, metrics) | Do math, generate content |
| `opik_tracing.py` / `logging.py` | Observability | Business logic |
| `prompts.py` | Prompt templates (incl. memory extraction/merge) | Any logic at all |
| `config.py` | Environment variables | Anything else |

## Multi-agent orchestration (LangGraph)

When `LANGGRAPH_ENABLED=true`, orchestration is a compiled LangGraph (`graph/pipeline.py`) on a **persistent event loop**:

1. **Route** — `route_start` branches: media → `media_route` (Router classify → HEALTH/LIFE), text → `text_intent` (intent classifier with memory context).
2. **Fan out in parallel** — `extract` ∥ `research` run concurrently (LangGraph edges), then converge on a `gate` node.
3. **Short-circuit** — if extraction short-circuits, `format_short_circuit` replies "I need the full policy document" without running the analyst.
4. **Analyst** — HEALTH → `HealthAnalyst`; LIFE → deterministic `life_calc` + `LifeAnalyst` (math stays in `calculator.py`).
5. **Memory chain (ordered)** — `memory_load → write_l0 → extract_l1 → (conditional) merge_l3 → update_l2`. `merge_l3` runs only when `extract_l1` produced ≥1 new atom.

Backends are **async** (`AsyncPostgresSaver` / `AsyncPostgresStore`) on one shared `AsyncConnectionPool`. Sync savers would block the event loop inside `graph.ainvoke`. The vector extension is created **before** `store.setup()`; both `setup()` calls are awaited (idempotent schema migrations).

The SDK callback is sync, so `handler.py` submits work via `asyncio.run_coroutine_threadsafe` to the persistent loop — never a per-message `asyncio.run` once the pool exists.

The legacy `Supervisor` remains as the flag-off fallback (`supervisor.py`).

```python
# Fan out independent work — LangGraph runs parallel edges for us
builder.add_edge("media_route", "extract")
builder.add_edge("media_route", "research")
builder.add_edge("extract", "gate")     # fan-in barrier
builder.add_edge("research", "gate")
```

## Rubric-driven page triage (opt-in)

When `use_rubric_triage=true` (set by the live handler for multi-page docs), the media path uses a **dual-track, page-by-page triage** (`graph/triage.py`) instead of the legacy head/middle/tail extraction:

- **Track A (text)** — every page is LLM-checked against the product's rubric in parallel; each returns a Pydantic-validated `PageTriageOutput` (partial fields + findings).
- **Track B (tables)** — ONE global `table_analyzer` call over the WHOLE Docling tables JSON. Cross-page tables (surrender schedules, premium projections) that Docling/TableFormer stitches structurally are never hallucinated by a page-local model.
- **Rubrics** are gold-standard checklists (`data/rubrics/{health,life,term}.json`) stored in the PostgresStore (namespaced, versioned) and seeded at startup. `prepare_triage` loads a rubric ONCE into graph state — the parallel nodes read state, zero repeat DB queries.
- **Deterministic calc** runs on the merged fields (exact-key contract, "LLM never does math"); **layman_writer** (second LLM, forbidden from recomputing) produces the plain-language verdict with per-item explanation + action from the rubric templates.

## Short-circuit extraction (no retry loops)

The extractor agent never burns retries confirming data isn't there. After the first pass, a triage LLM returns `{"data_exists_in_document": false}` and the agent **short-circuits** — returning partial data + a missing list to the supervisor, which replies "I need the full policy document." Hard cap: **1 retry**.

This handles the real case where a user uploads a premium receipt or a 2-page brochure instead of the full 40-page policy.

## Document routing (Gap-free input handling)

- `.pdf` → **Docling** (layout + TableFormer tables + OCR) → text-LLM over markdown, table-LLM over tables JSON, vision only as single-page fallback.
- `.jpg/.jpeg/.png` (photos) → **bypass Docling**, go straight to the vision path (a 3GB model pipeline is overkill for one photo).
- Unknown → vision fast path.

## The LLM never sends messages

Only `handler.py` calls `message.reply()`. No agent touches channels directly. The SDK routes to the correct channel automatically.

## Channel-agnostic core

The agents, calculators, and state have zero awareness of whether the user is on email or Telegram. Only `handler.py` touches channels, via `message.reply()` which the SDK routes.

No branching on channel type. Ever.

## Fail fast, fail honestly

- If extraction is partial, the agent says exactly what's missing and asks for it.
- If the document isn't a policy (receipt, brochure), the agent says so.
- If the data is genuinely insufficient, the verdict says "not enough data to determine" — it never fabricates a conclusion.

Silent failures kill demos. Loud, honest failures get fixed before the demo.

## State & memory

**LangGraph mode** (`LANGGRAPH_ENABLED=true`): thread state persists via the Postgres checkpointer; long-term memory lives in the Postgres `MemoryStore`, namespaced per stable `user_id` (from the `users` table, shared across email + Telegram):

- **L0 raw** `(user_id, "l0", thread_id)` — raw messages/events, no LLM, every turn.
- **L1 atoms** `(user_id, "l1", "atoms")` — atomic facts, keyed by content hash, LLM-extracted only on meaningful events.
- **L2 scenario** `(user_id, "l2", "scenarios")` — per-policy bundles, semantic-searchable.
- **L3 persona** `(user_id, "l3", "profile")` — merged profile, only after L1 produced new atoms.

**Legacy mode** (flag off): SQLite via `store.py`, managed by `case_manager.py`. The Caspian SDK provides **no agent-state API** — it's a channel/messaging SDK (`connect_*`, `on_message`, `reply`, `list_conversations`, `backfill`, `events`). Our own state layer is the correct choice; `list_messages`/`backfill` can rebuild conversation state on restart.

## Safety rails (guardrails)

- **Input rails** on user text AND policy-document text (a crafted PDF can contain prompt injection — the most dangerous surface).
- **Output rail** on drafted letters: disclaimer appended, overpromising claim language sanitized.
- Blocking raises `GuardrailValidationError` (never a sentinel string); the handler catches it and replies safely without invoking downstream models.
- Rails are **opt-in** via `GUARDRAILS_ENABLED` — zero latency when off.

## Observability

- **Opik** (opt-in): every LLM call traced with inputs/outputs/model; one trace per message with nested spans per agent.
- **Structured logging**: every record carries the conversation's correlation ID via a contextvar; third-party loggers are tolerated by `SafeFormatter`.

## Evaluation harness (`evals/`)

Each agent is scored against a labeled gold dataset via Opik's `evaluate()`. Deterministic metrics run always (free); an LLM judge runs only with `--live`.

- **Datasets** are gold JSON files under `evals/data/` (`{"version": N, "rows": [...]}`). Seeding does `clear()` + `insert()` so the dataset is pinned to the current gold (Opik dedupes by content hash — plain inserts accumulate stale rows across gold edits).
- **Tasks** wrap async agents for Opik's sync `ThreadPoolExecutor`: each task creates a fresh `asyncio` loop (never reuse a loop across threads) and builds agents inside it so OpenAI/httpx clients belong to that loop.
- **Docling cache** (`evals/data/docling_cache/`): pre-parsed PDF results so the metric loop never re-runs Docling/OCR. Populated by `scripts/seed_evals.py`.
- **Metrics** are deterministic by default (`NormalizedFieldAccuracy` with currency/alias normalization, `WhitelistEnforcement`, `RequiredFieldsPresent`, `ShortCircuitCorrectness`, gates). The LLM judge (`RobustLLMJudge`) prompts for JSON and parses tolerantly — it never depends on provider `response_format` support (Featherless returns content in `reasoning`).
- **CLI**: `uv run python -m policydecoder.evals.run_all --agent X [--live]` or `--all`.
- Deterministic metrics gate CI; judge scores are advisory.

## Tests are written first

Every feature starts as a failing test. The test defines the contract. Then we write the minimum code to make it pass.

Tests never call the real LLM, real channels, or real timers. `conftest.py` has fakes for all three, and autouse fixtures force guardrails/opik/docling **off** so the suite never hits the network.

Run `uv run pytest` before any commit. If it's red, the commit doesn't happen.

## CI & quality gates

Every push/PR runs (`.github/workflows/ci.yml`):

```bash
uv run ruff check src tests scripts   # lint
uv run ruff format --check src tests scripts  # format
uv run mypy src/policydecoder          # types
uv run pytest -q                      # tests
```

Pre-commit hooks enforce the same locally.

## Anti-patterns we reject

| Pattern | Why not |
|---|---|
| LLM calls tools directly | Security risk. Harness gates all execution. |
| LLM does arithmetic | Hallucination risk. Python does math. |
| Persistent Docling converter singleton | Pins 4GB+ VRAM. Per-parse lifecycle + `torch.cuda.empty_cache()`. |
| Full document in one LLM prompt | Context blowout. Chunked text + structured tables + single-page vision fallback. |
| Researcher citing any domain | Fact-drift. Whitelist enforced at the Python layer. |
| Retry loops on missing extraction | Wastes vision calls. Short-circuit on triage. |
| Channel branching in handler | Defeats the SDK. Use `message.reply()`. |
| Bare `except Exception` | Hides bugs. Catch specific errors. |

## Quick reference

```python
# DO
message.reply(text)                                  # SDK routes to correct channel
case = case_manager.get(conversation_id)             # state via manager
result = calculator.xirr(cash_flows)                 # Python for math
analysis = await supervisor.process_media(urls, input_path=...)  # legacy orchestrator
result = await graph.ainvoke(input_state, config)    # LangGraph orchestrator (default)
parsed = docling_parser.parse_document(path)          # PDF → markdown/tables

# DON'T
if message.channel == "email": ...                    # no channel branching
converter = DocumentConverter()  # module-level          # no GPU singleton
result = llm.analyze_policy(extract(pdf))            # no math in LLM
llm.call_tool("send_email", ...)                     # LLM never sends
raise Exception("broke")                             # catch specific errors
```
