# Policy Decoder → honest-policy-advisor

AI agent that gives an honest second opinion on health and life insurance: reads the policy document (PDF/photo), tells you if you were mis-sold, flags what's alarming or worth changing, and drafts the complaint letter to get your money back. Works for policies you own AND policies you're planning to buy.

## Hackathon

Caspian AI Agent Hackathon (15-day, online). Agent must use caspian-sdk and run on 2+ channels through a single on_message handler.

## What we're building

The agent receives an insurance policy PDF via email attachment or Telegram photo. It uses a vision model to extract the key details (policy name, premium, charges, surrender values), runs deterministic Python calculations (XIRR, term+SIP comparison), and uses the LLM to decide if the policy was mis-sold, flag alarming terms (waiting periods, exclusions, co-pay, room rent caps for health; surrender charges and low returns for life), and draft the appropriate complaint letter. The verdict must be honest — including "this policy is fine" when it is.

Channels: email (formal, PDF attachments, complaint letters) + Telegram (quick questions, photo uploads).

## Project structure

```
policy-decoder/
├── src/policydecoder/    # the package
│   ├── main.py           # entry point
│   ├── handler.py        # one on_message handler
│   ├── extractor.py      # vision model PDF reading
│   ├── calculator.py     # pure Python financial math
│   ├── analyzer.py       # LLM analysis + letter drafting
│   ├── case_manager.py   # state machine
│   ├── store.py          # SQLite persistence
│   ├── email_link.py     # Gmail compose links
│   ├── prompts.py        # prompt templates
│   └── config.py         # env config
├── tests/
├── scripts/
├── PLAN.md
├── ENGINEERING.md
├── HACKATHON.md
└── AGENTS.md             # this file
```

## Key rules

- LLM never does math. calculator.py handles all financial computation.
- LLM never sends messages. handler.py and alert_system.py handle that.
- Tests first. `uv run pytest` before any commit.
- No channel branching in handler. message.reply() routes automatically.

## SDK reference

Live integration guide: https://api.trycaspianai.com/SKILL.md
SDK repo: https://github.com/TryCaspian/caspian-sdk
