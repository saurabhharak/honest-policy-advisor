# Engineering rules for policy-decoder

These are the rules every line of code in this project follows. They're not aspirational. They exist because we've seen what breaks during a demo.

## The agent harness pattern

The LLM proposes. The harness executes. This is the most important rule in the project.

The LLM reads a policy PDF and says "this looks like a ULIP with a 4% premium allocation charge and a 5-year lock-in." The harness takes that finding and decides what to do with it. The LLM never sends a message, never calls an API, never writes to the database.

```
BAD:  LLM → calls send_email() → email sent
GOOD: LLM → "this is mis-sold, draft a complaint" → harness validates → harness sends → harness logs
```

## The LLM never does math

XIRR, compound interest, surrender value calculations, SIP projections. None of this touches the LLM. All of it lives in calculator.py as pure Python functions.

Why: LLMs hallucinate numbers. A hallucinated surrender value that's 10% too high is terrible financial advice. A Python function with the same inputs gives the same output every time.

```
BAD:  "The LLM calculated your XIRR as 3.8%"
GOOD: calculator.xirr(cash_flows) → 0.038 → passed to LLM for the report
```

## Single responsibility per module

| Module | Its one job | What it does NOT do |
|---|---|---|
| handler.py | Route messages to intents | Manage state, generate content, do math |
| extractor.py | Read PDFs via vision model, return JSON | Analyze, calculate, draft letters |
| calculator.py | Financial math (XIRR, comparisons) | LLM calls, message sending, state |
| analyzer.py | LLM analysis + letter drafting | Math, PDF parsing, state management |
| case_manager.py | State machine + storage | Send messages, call LLM |
| store.py | SQLite persistence | Business logic |
| prompts.py | Prompt templates | Any logic at all |
| config.py | Environment variables | Anything else |

## Open/closed state router

The handler routes via a dict, not if/elif chains. Adding a new state means adding a new handler function and registering it. The router code doesn't change.

```python
STATE_ROUTER = {
    CaseState.POLICY_RECEIVED: handle_policy_received,
    CaseState.ANALYZED: handle_analyzed,
    # New states go here, nowhere else
}
```

## Channel-agnostic core

extractor.py, calculator.py, analyzer.py, and case_manager.py have zero awareness of whether the user is on email or Telegram. Only handler.py and alert_system.py touch channels, and they use message.reply() which the SDK routes automatically.

No branching on channel type. Ever.

## Fail fast

If the vision model can't extract the surrender value table, we ask the user for it directly. If the XIRR calculation gets bad inputs, we return an error and ask for clarification. If the LLM's confidence is below 0.7, we ask the user to rephrase.

Silent failures kill demos. Loud failures get fixed before the demo.

## In-memory state with SQLite backup

A dict in memory is the primary store. SQLite is the backup that survives restarts. No Redis, no Postgres, no vector database. The demo runs for 3 minutes. A dict is fine.

Post-hackathon, swap case_manager.py for a real database. Zero other files change.

## One LLM, two roles

One model for intent classification and content generation. Not two models, not a multi-agent swarm. If classification is too slow or expensive, switch to a cheaper model for that one call. That's a one-line change.

## Tests are written first

Every feature starts as a failing test. The test defines the contract. Then we write the minimum code to make it pass.

Tests never call the real LLM, real channels, or real timers. conftest.py has fakes for all three.

Run `uv run pytest` before any commit. If it's red, the commit doesn't happen.

## What we deliberately skip

- Web dashboard (the demo is terminal + two channels)
- Multi-tenant support (one user per demo)
- PDF generation for reports (plain text is fine)
- Rate limiting (single user, demo context)
- Custom email domain (free instant inbox works)
- Scheduled background jobs (demo simulates time passing)

If removing it doesn't break the 3-minute demo, we don't build it.

## Observability

Every action gets logged with structured data:

```
[2026-08-09T14:30:00] CASE:conv_abc123 ACTION:STATE_CHANGE POLICY_RECEIVED → ANALYZED
[2026-08-09T14:30:01] CASE:conv_abc123 ACTION:EXTRACTION policy_name=LIC_Jeevan_Anand premium=50000
[2026-08-09T14:30:02] CASE:conv_abc123 ACTION:CALCULATION xirr=0.038 comparison_sip=0.112
[2026-08-09T14:30:03] CASE:conv_abc123 ACTION:MESSAGE_SENT email, 1200 chars, complaint draft
```

When the demo breaks during rehearsal, these logs say exactly where.

## Anti-patterns we reject

| Pattern | Why not |
|---|---|
| LLM calls tools directly | Security risk. Harness gates all execution. |
| Bare except Exception | Hides bugs that kill the demo. Catch specific errors. |
| Channel branching in handler | Defeats the SDK. Use behavior_prompt() for tone. |
| Giant system prompt | Leads to unpredictable behavior. Use structured prompts. |
| execute_anything tool | Never. Every action is a purpose-built function. |
| LLM doing arithmetic | Hallucination risk. Python does math. |

## Quick reference

```python
# DO
message.reply(text)                              # SDK routes to correct channel
case = case_manager.get(conversation_id)         # state via manager
result = calculator.xirr(cash_flows)             # Python for math
draft = analyzer.draft_complaint(extracted, calc) # LLM for text

# DON'T
if message.channel == "email": ...               # no channel branching
case["policy_name"] = ...                         # no direct mutation
llm.call_tool("send_email", ...)                  # LLM never sends
raise Exception("broke")                          # catch specific errors
```
