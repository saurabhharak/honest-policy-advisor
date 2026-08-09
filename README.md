# honest-policy-advisor

An honest second opinion on your health and life insurance — for policies you already own and ones you're planning to buy. It decodes the policy document, flags what's alarming, tells you what to change, and drafts the complaint letter when you've been mis-sold.

Built for the [Caspian AI Agent Hackathon 2026](https://github.com/TryCaspian/caspian-sdk).

## What it does

Send a photo of a policy document (Telegram) or forward the PDF (email) — whether it's a policy you own or one you're about to buy. The agent:

1. **Decodes the document** — Docling parses the PDF (layout + tables + OCR), then specialist agents extract the key fields: premium, cover, term, charges, surrender values, benefit illustration (life) or exclusions, waiting periods, co-pay, room rent caps (health).
2. **Runs the numbers** — deterministic Python computes XIRR vs. a term plan + SIP for life policies; claim ratios, premium-vs-cover value and red-flag terms for health policies.
3. **Gives an honest opinion** — what's alarming, what you should change, or when the policy is genuinely fine.
4. **Drafts the right letter** — free-look cancellation, insurer complaint, or Ombudsman escalation, with a Gmail compose link.

The verdict is always honest — including "this policy is fine" when it is.

## Architecture

A **supervisor + specialist agents** pipeline. The supervisor routes, fans out independent agents in parallel, and runs the dependent ones sequentially.

```
User message (email / Telegram)
  │
  ▼
handler.py ── one on_message handler (channel-agnostic)
  │
  ▼
Supervisor
  ├─ Router Agent        — classify document (HEALTH / LIFE / TERM)
  ├─ Extractor Agent     — Docling PDF parse → text/table LLM extraction → short-circuit on missing data
  ├─ Researcher Agent    — fetch live info (whitelisted domains: irdai.gov.in, joinditto.in, beshak.org)
  ├─ Health Analyst      — deterministic scoring + honest verdict (calls calculators)
  ├─ Life Analyst        — XIRR + term+SIP + surrender (calls calculators)
  └─ Letter Drafter      — free-look / complaint / ombudsman letters
Tools: calculators (pure math), insurer_data (IRDAI benchmark), email_link, fetch
Safety: NeMo Guardrails on every input/output
Observability: Opik tracing + structured logging with correlation IDs
```

**Key principle: the LLM never does math.** All financial computation lives in pure Python (`calculator.py`, `health_calculator.py`). The LLM only interprets computed numbers and writes prose.

## Channels

- **Email**: forward your policy PDF as an attachment
- **Telegram**: send a photo of the policy document, or ask a quick question

Both channels hit the same `on_message` handler. No channel-specific logic.

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- A Caspian API key (free)
- A Telegram bot token (from @BotFather)
- An OpenAI-compatible API key (Featherless works)

### Install

```bash
git clone <repo-url>
cd policy-decoder
uv sync --all-extras
```

Optional extras (each is opt-in):

```bash
uv sync --extra docling        # PDF parsing (heavy: pulls PyTorch models)
uv sync --extra guardrails     # NeMo input/output safety rails
uv sync --extra observability  # Opik LLM tracing
```

### Configure

```bash
cp .env.example .env
# Fill in your keys. See .env.example for all options.
```

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `CASPIAN_API_KEY` | yes | — | Caspian gateway auth |
| `TELEGRAM_BOT_TOKEN` | yes | — | Telegram bot |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | yes | — | LLM + vision endpoint |
| `LLM_MODEL` / `VISION_MODEL` | no | gpt-4o-mini / Qwen3-VL | model ids |
| `GUARDRAILS_ENABLED` | no | false | NeMo rails |
| `OPIK_ENABLED` / `OPIK_URL` / `OPIK_API_KEY` | no | false | Opik tracing |
| `DOCLING_ENABLED` / `DOCLING_TEXT_MODEL` | no | false | Docling PDF parse |

### Run

```bash
uv run python -m policydecoder.main
```

You should see:

```
Policy Decoder ONLINE
  Email:    policydecoder@agents.trycaspianai.com
  Telegram: @YourBotUsername
  LLM:      deepseek-ai/DeepSeek-V4-Flash
  Vision:   Qwen/Qwen3-VL-8B-Instruct
```

### Test a policy file (no channels needed)

```bash
uv run python scripts/run_policy_file.py <path-to-policy.pdf>
```

Runs the full pipeline (router → Docling → extractor → analyst) on a local PDF and prints the verdict. This is the fastest way to verify the analysis path.

### Generate test policies

Public insurer specimen PDFs identify products but leave the schedule blank. The generator fills realistic values and appends a benefit illustration:

```bash
uv run python scripts/download_policies.py     # download real specimens (Playwright)
uv run python scripts/generate_test_policies.py # build full-schedule synthetic policies
```

Outputs land in `insurance_policies/` (gitignored — regenerable).

### Run tests

```bash
uv run pytest
```

## How the analysis works

### Health policies

1. **Extraction** — Docling parses the PDF; specialist LLMs extract sum insured, premium, room rent cap, co-pay, waiting periods, sub-limits, exclusions, restoration, network size.
2. **Deterministic scoring** (`health_calculator.py`) — flags room-rent caps, co-pay >20%, long waiting periods, hidden sub-limits, missing restoration, small networks, and sum-insured adequacy vs. city tier.
3. **Benchmark** — the insurer's IRDAI FY2024-25 metrics (ICR, solvency, complaints) are looked up from a curated dataset.
4. **Honest verdict** — the analyst writes the verdict from the computed flags, citing the benchmark.

### Life policies

1. **Extraction** — policy name, premium, term, sum assured, and the benefit illustration (4%/8% maturity values).
2. **Deterministic math** (`calculator.py`) — XIRR of the benefit-illustration cash flows, a term+SIP alternative, opportunity cost, and surrender loss.
3. **Verdict** — mis-sold if it's a ULIP/endowment returning below what a term+SIP would give, or if a term plan was replaced with an investment product.
4. **Action** — free-look cancellation if within the window, else complaint letter.

### Researcher

The Researcher agent fetches live market/regulatory context on demand (e.g. Ditto's "how to choose" guides, IRDAI reports) — restricted to a **whitelist** (`irdai.gov.in`, `joinditto.in`, `beshak.org`) enforced at the Python layer, so no fact-drift from unvetted pages.

## Escalation paths

1. **Free-look cancellation** — within 15-30 days of receiving the policy, cancel with a full refund.
2. **Insurer complaint** — formal letter to the insurance company's grievance cell.
3. **Bima Bharosa** — IRDAI's complaint portal (bimabharosa.irdai.gov.in), 15-day SLA.
4. **Insurance Ombudsman** — free, no lawyer needed, awards up to ₹30 lakh.

## Security & safety

- **NeMo Guardrails** (opt-in): jailbreak/prompt-injection detection on user input and policy-document text; letter-output disclaimer + overpromise sanitization.
- **No secrets in repo** — `.env` is gitignored; `.env.example` documents all variables.
- **Source whitelist** — the researcher only cites vetted domains.

## Observability

- **Opik tracing** (opt-in): every LLM call across all agents is traced with inputs, outputs, model, and a per-message correlation ID. Browse traces in the Opik UI.
- **Structured logging**: all logs carry the conversation's correlation ID, tying every record to its trace.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the dev workflow and conventions (tests-first, ruff, mypy, pre-commit).

## License

MIT
