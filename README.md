# honest-policy-advisor

An honest second opinion on your health and life insurance — for policies you already own and ones you're planning to buy. It decodes the policy document, tells you what's alarming, suggests what to change, and drafts the complaint letter when you've been mis-sold.

Built for the Caspian AI Agent Hackathon 2026.

## What it does

Send a photo of a policy document (Telegram) or forward the PDF (email) — whether it's a policy you own or one you're about to buy. The agent:

1. Extracts the key details — premium, cover, term, charges, surrender values, benefit illustration (life) or exclusions, waiting periods, co-pay, room rent caps (health)
2. Runs the numbers — XIRR vs. a term plan + SIP for life policies; claim ratios, premium-vs-cover value and red-flag terms for health policies
3. Gives an honest opinion — what's alarming, what you should change, or when the policy is genuinely fine
4. Drafts the right letter — free-look cancellation, insurer complaint, or Ombudsman escalation

## Channels

- Email: send your policy PDF as an attachment
- Telegram: send a photo of the policy document

Both channels hit the same handler. No channel-specific logic.

## Setup

### What you need

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

### Configure

```bash
cp .env.example .env
# Fill in your keys
```

### Run

```bash
uv run python -m policydecoder.main
```

You should see:

```
Policy Decoder ONLINE
  Email:    policydecoder@agents.trycaspianai.com
  Telegram: @YourBotUsername
  LLM:      ...
  Vision:   ...
```

### Test

```bash
# Send a test email
curl -s -X POST https://api.trycaspianai.com/v1/test-emails \
  -H "Authorization: Bearer $CASPIAN_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"text":"Can you check my LIC Jeevan Anand policy? I pay ₹50,000/year."}'
```

### Run tests

```bash
uv run pytest
```

## How the analysis works

The agent never lets the LLM do math. Here's the split:

**LLM (vision model):** reads the policy PDF, extracts structured JSON — premium, cover, term, charges, surrender values, benefit illustration (life) or exclusions, waiting periods, co-pay, room rent caps (health).

**Python (calculator.py):** computes XIRR using scipy, compares with term+SIP returns, calculates surrender loss and opportunity cost.

**LLM (analyzer):** receives the extracted data and calculation results, gives an honest verdict — mis-sold, alarming terms to fix, or fine as-is — picks the escalation path and drafts the letter.

## Escalation paths

Depending on your situation:

1. **Free-look cancellation** — if you're within 15-30 days of receiving the policy document, you can cancel with a full refund
2. **Insurer complaint** — formal letter to the insurance company's grievance cell
3. **Bima Bharosa** — IRDAI's complaint portal (bimabharosa.irdai.gov.in), 15-day SLA
4. **Insurance Ombudsman** — free, no lawyer needed, awards up to ₹30 lakh

## License

MIT
