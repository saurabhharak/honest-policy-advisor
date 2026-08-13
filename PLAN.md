# Policy Decoder — build plan

## What this is

An AI agent that reads your life insurance policy (the PDF the insurer gave you), tells you whether you were mis-sold, calculates exactly how much you're losing, and drafts the complaint letter to get your money back.

## Why this exists

You bought a policy because a relative or bank RM said "it's like an FD but better." Years later you find out it's a ULIP or endowment plan returning 3-4% when a term plan + SIP would have given you 11-12%. IRDAI got 26,667 mis-selling complaints in 2024-25. RBI's own report flags it. 38% of life insurance payouts in FY26 were people giving up and surrendering at a loss.

Nobody reads the 45-page policy document. That's the whole trick.

## How it qualifies for the hackathon

- Uses caspian-sdk: CommClient, on_message, connect_email, connect_telegram
- Two channels, one handler: email for the PDF and formal letters, Telegram for quick questions
- All code written during the hackathon window
- Public repo with setup instructions

## Channels

**Email** (connect_email): user forwards their policy PDF as an attachment. Agent sends back the full analysis report and drafted complaint letters.

**Telegram** (connect_telegram): user sends a photo of the policy or asks quick questions. Agent replies with the key numbers and next steps.

## Architecture (current)

```
user sends policy PDF (email attachment or Telegram photo)
        │
        ▼
  handler.py ── the one on_message handler (channel-agnostic)
        │
        ▼
  LangGraph pipeline (LANGGRAPH_ENABLED) ── legacy Supervisor is the flag-off fallback
        │
        ├─▶ Router Agent ── Docling/heuristic classify → HEALTH / LIFE / TERM
        │
        ├─▶ Extractor Agent ── Docling (layout+tables+OCR) → text/table LLM
        │                     extraction → short-circuit on genuinely missing data
        │
        ├─▶ Rubric triage (multi-page) ── dual track: per-page rubric review
        │                     ∥ global table analyzer; findings accumulate
        │
        ├─▶ calculators ── pure Python. XIRR, term+SIP comparison, surrender
        │                     value, opportunity cost, health scoring.
        │                     The LLM never does math.
        │
        ├─▶ Analyst agents ── LLM writes the honest verdict from computed
        │                     numbers + rubric findings (never recomputes)
        │
        ├─▶ Letter Drafter ── free-look / complaint / ombudsman letters
        │
        └─▶ Memory chain ── L0-L3 layered memory (raw → atoms → scenarios → persona)
                              per stable user_id, in Postgres (pgvector)
```

The old vision-only linear path (`extractor.py` → `analyzer.py` → `case_manager.py`) still exists for photos and as the non-LangGraph fallback.

## Case state machine

```
IDLE
  │
  ▼
POLICY_RECEIVED ── user sent a PDF or photo
  │
  ▼
ANALYZED ── extraction + calculation complete, report sent
  │
  ├─▶ FREE_LOOK ── policy is within 15-30 day free-look window
  │     └─▶ CANCELLATION_DRAFTED
  │
  ├─▶ COMPLAINT ── past free-look, draft insurer complaint
  │     └─▶ COMPLAINT_SENT
  │           └─▶ ESCALATION ── insurer didn't respond in 15 days
  │                 └─▶ OMBUDSMAN_DRAFTED
  │
  └─▶ RESOLVED
```

## What goes into the analysis

The extractor pulls from the policy PDF:

1. Policy name and type (ULIP, endowment, money-back, whole life)
2. Annual premium and premium payment term
3. Policy term and sum assured
4. All charges (premium allocation, policy admin, mortality, fund management)
5. The surrender value table
6. The benefit illustration (4% and 8% projected values)

The calculator then computes:

1. XIRR of the policy using the benefit illustration cash flows
2. What a term plan (₹1 crore cover) would cost for the same person
3. What the remaining premium invested in a Nifty 50 index fund would return
4. The gap between the two
5. Current surrender value and how much the user loses if they exit today

The analyzer then decides:

1. Is this a mis-sold policy? (ULIP/endowment sold as investment)
2. Is the user within the free-look period?
3. What's the right escalation path?
4. Draft the appropriate letter (free-look cancellation, insurer complaint, Bima Bharosa, or Ombudsman)

## Scope limits

In scope (current):
- ULIP and endowment policies (the two most mis-sold types) + term plans
- **Health insurance** — full rubric-based review (room-rent caps, co-pay, waiting periods, sub-limits, restoration)
- PDF upload via email or Telegram photo
- Extract → calculate → analyze → draft → track
- Free-look cancellation and Bima Bharosa complaint paths
- Multi-page rubric triage + L0-L3 memory + Opik evaluation

Not in scope:
- Claim rejection disputes (different problem)
- Every insurer's surrender formula (we extract it from the PDF)

## File structure (current)

```
policy-decoder/
├── README.md
├── .env.example
├── pyproject.toml
├── src/
│   └── policydecoder/
│       ├── main.py            # entry point, wires channels + graph/supervisor
│       ├── handler.py         # the one on_message handler
│       ├── graph/             # LangGraph pipeline (nodes, triage, memory, identity, backends)
│       ├── agents/            # specialist agents (extractor, researcher, analysts, drafter)
│       ├── evals/             # Opik eval harness (datasets, tasks, metrics, run_all)
│       ├── docling_parser.py  # PDF → markdown/tables (per-parse lifecycle)
│       ├── extractor.py       # vision-model extraction (photo path + fallback)
│       ├── calculator.py      # pure Python financial math
│       ├── health_calculator.py  # pure Python health scoring
│       ├── analyzer.py        # shared LLM prompt executor + draft methods
│       ├── router.py          # document classifier
│       ├── schemas.py         # Pydantic extraction schemas
│       ├── case_manager.py / store.py  # legacy SQLite state (flag-off fallback)
│       └── config.py          # env config
├── tests/
├── scripts/                   # run_policy_file, live_test_graph, trigger_policy_flow, seed_evals, ...
├── HACKATHON.md
├── PLAN.md
├── ENGINEERING.md
└── AGENTS.md
```

## LLM setup

One LLM for two roles (same as bodyguard):
- Classification/extraction: fast, structured output
- Letter drafting: longer, more detailed

Vision model for PDF reading (Qwen3-VL or similar via OpenRouter/Featherless).

## Demo script (3 minutes)

**0:00-0:30** — User sends policy PDF via Telegram. "My uncle sold me this LIC policy. ₹50,000/year. Is this good?"

**0:30-1:00** — Agent extracts and calculates. Replies: "This is LIC Jeevan Anand, an endowment plan. Your XIRR is 3.8%. A term plan + SIP would give 11.2%. You're losing ₹8.6 lakhs over 15 years."

**1:00-1:30** — Agent asks: "When did you buy this?" User says "2 years ago." Agent: "You're past the free-look window. But you can still surrender and file a mis-selling complaint. Here's your letter."

**1:30-2:30** — Agent sends the drafted complaint via email with a Gmail compose link. User reviews and sends from their own email.

**2:30-3:00** — Agent: "I've set a 15-day follow-up. If the insurer doesn't respond, I'll draft the Bima Bharosa escalation."

## Timeline

| Day | What gets done |
|---|---|
| Day 1 | Project scaffold, config, connect channels, basic handler. Extractor for policy PDFs. |
| Day 2 | Calculator (XIRR, comparison), analyzer (mis-selling detection), letter drafting. |
| Day 3 | Polish, test full flow, record demo, push repo, submit. |

## Risks

| Risk | What we do about it |
|---|---|
| PDF is too complex for vision model | Fall back to asking the user for 5 key numbers manually |
| LLM hallucinates math | All math is in calculator.py. LLM only formats results. |
| Demo latency too high | Pre-compute a sample analysis. Show the flow on a small PDF. |
| Surrender value logic varies by insurer | Extract the table from the PDF itself, don't hardcode formulas. |
