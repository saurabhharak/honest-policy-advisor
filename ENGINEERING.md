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
| `supervisor.py` | Orchestrate agents; fan out parallel work | Do math, generate content |
| `agents/extractor_agent.py` | Parse + extract fields; short-circuit on missing data | Analyze, draft letters |
| `agents/researcher_agent.py` | Fetch whitelisted sources; summarize | Compute policy numbers |
| `agents/health_analyst.py` / `life_analyst.py` | Write honest verdict from computed data | Do math |
| `agents/letter_drafter.py` | Draft letters | Analyze |
| `docling_parser.py` | PDF → markdown/tables (per-parse lifecycle) | Anything else |
| `calculator.py` / `health_calculator.py` | Pure financial math | LLM calls, state |
| `case_manager.py` | State machine | Send messages, call LLM |
| `store.py` | SQLite persistence | Business logic |
| `guardrails.py` | Input/output safety rails | Anything else |
| `opik_tracing.py` / `logging.py` | Observability | Business logic |
| `prompts.py` | Prompt templates | Any logic at all |
| `config.py` | Environment variables | Anything else |

## Multi-agent orchestration

The supervisor is the orchestrator. It:

1. **Classifies** the document (Router → HEALTH/LIFE/TERM).
2. **Fans out independent agents in parallel** (`asyncio.gather`) — e.g. Extractor + Researcher run concurrently, cutting end-to-end latency.
3. **Runs dependent agents sequentially** — the analyst waits for both, the drafter waits for the verdict.
4. **Sets correlation ID + starts the Opik trace** per message, so every agent's spans nest under one trace.

```python
# Fan out independent work — never run these serially
extract_task = self.extractor.run(...)
research_task = self.researcher.run(...)
extraction, findings = await asyncio.gather(extract_task, research_task)
```

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

## State

SQLite via `store.py`, managed by `case_manager.py`. The Caspian SDK provides **no agent-state API** — it's a channel/messaging SDK (`connect_*`, `on_message`, `reply`, `list_conversations`, `backfill`, `events`). Our own state layer is the correct choice; `list_messages`/`backfill` can rebuild conversation state on restart.

## Safety rails (guardrails)

- **Input rails** on user text AND policy-document text (a crafted PDF can contain prompt injection — the most dangerous surface).
- **Output rail** on drafted letters: disclaimer appended, overpromising claim language sanitized.
- Blocking raises `GuardrailValidationError` (never a sentinel string); the handler catches it and replies safely without invoking downstream models.
- Rails are **opt-in** via `GUARDRAILS_ENABLED` — zero latency when off.

## Observability

- **Opik** (opt-in): every LLM call traced with inputs/outputs/model; one trace per message with nested spans per agent.
- **Structured logging**: every record carries the conversation's correlation ID via a contextvar; third-party loggers are tolerated by `SafeFormatter`.

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
analysis = await supervisor.process_media(urls, input_path=...)  # orchestrator
parsed = docling_parser.parse_document(path)          # PDF → markdown/tables

# DON'T
if message.channel == "email": ...                    # no channel branching
converter = DocumentConverter()  # module-level          # no GPU singleton
result = llm.analyze_policy(extract(pdf))            # no math in LLM
llm.call_tool("send_email", ...)                     # LLM never sends
raise Exception("broke")                             # catch specific errors
```
