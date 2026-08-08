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

## Architecture

```
user sends policy PDF (email attachment or Telegram photo)
        │
        ▼
  handler.py ── the one on_message handler, routes by intent
        │
        ├─▶ extractor.py ── vision model reads the PDF, outputs structured JSON
        │                     (policy name, premium, term, sum assured,
        │                      surrender value table, charges)
        │
        ├─▶ calculator.py ── pure Python. XIRR of the policy. Term+SIP
        │                     comparison. Surrender value. Opportunity cost.
        │                     The LLM never does math.
        │
        ├─▶ analyzer.py ── LLM receives the extracted JSON + calculator
        │                    results. Decides: mis-sold or not? Which
        │                    clauses are problems? What escalation path?
        │                    Drafts the letter.
        │
        └─▶ case_manager.py ── tracks where each user is in the process
                               (received PDF → analyzed → letter drafted →
                                complaint filed → resolved)
```

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

In scope:
- ULIP and endowment policies (the two most mis-sold types)
- PDF upload via email or Telegram photo
- Extract → calculate → analyze → draft → track
- Free-look cancellation and Bima Bharosa complaint paths

Not in scope:
- Term insurance (nothing to decode)
- Health insurance (different rules)
- Claim rejection disputes (different problem)
- Every insurer's surrender formula (we extract it from the PDF)

## File structure

```
policy-decoder/
├── README.md
├── .env.example
├── pyproject.toml
├── src/
│   └── policydecoder/
│       ├── __init__.py
│       ├── main.py          # entry point, connects channels
│       ├── handler.py       # the one on_message handler
│       ├── extractor.py     # vision model PDF extraction
│       ├── calculator.py    # pure Python financial math
│       ├── analyzer.py      # LLM analysis + letter drafting
│       ├── case_manager.py  # state machine + storage
│       ├── store.py         # SQLite persistence
│       ├── email_link.py    # Gmail compose links
│       ├── prompts.py       # all prompt templates
│       └── config.py        # env config
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_calculator.py
│   ├── test_extractor.py
│   └── test_handlers.py
├── scripts/
│   └── verify.sh
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
