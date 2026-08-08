# Caspian AI Agent Hackathon — what you need to know

## The brief

Build an AI agent that uses caspian-sdk and runs on at least two channels through a single on_message handler. Any domain, any use case. Judged on creativity and whether it actually works.

## Dates

| What | When |
|---|---|
| Hacking window | Jul 28 to Aug 11, 2026 |
| Registration closes | Aug 10, 2026 00:00 IST |
| Submit by | Aug 11, 2026 23:59 IST (Devpost, stricter deadline) |
| Judging | Aug 12-13 |
| Winners | Aug 20 |

Target Aug 11. The platforms disagree on the deadline. Devpost is stricter. Don't wait for the 17th.

## Who can enter

Students, working professionals, anyone 18+. Solo or teams of 2. Free to enter.

## What to submit

1. Public GitHub repo (must stay public through judging)
2. Demo video, max 3 minutes, on YouTube/Vimeo/Loom. Must show the agent on 2+ channels.
3. All code written during the hackathon window
4. Submission in English
5. Setup instructions in the repo

## Unstop form

Three fields:
1. "Have you starred the GitHub repo" → Yes
2. GitHub link → your public repo
3. Video link → your demo video

## Prizes

- Winner: ₹20,000 + $1,500 Caspian credits
- 1st runner up: $300 Caspian credits
- 2nd runner up: $200 Caspian credits

## Contacts

- Ayush: ayush@trycaspianai.com (starter credits, questions)
- Rushant: rushant@saasden.club

---

## SDK reference

### Setup

```bash
# Get an API key (free, no signup)
curl -s -X POST https://api.trycaspianai.com/v1/projects/sandbox \
  -H 'Content-Type: application/json' -d '{"name":"policy-decoder"}'

# .env
CASPIAN_API_KEY=comm_sandbox_...
CASPIAN_BASE_URL=https://api.trycaspianai.com
```

```bash
pip install caspian-sdk
```

### Minimal agent

```python
from caspian_sdk import CommClient

client = CommClient()
email = client.connect_email(username="policydecoder")
telegram = client.connect_telegram(bot_token="...")

@client.on_message
def handle(message):
    answer = your_logic(message.text)
    message.reply(answer)

client.listen()
```

### Live channels (as of Aug 8)

| Channel | Setup | Cost |
|---|---|---|
| Email | connect_email(username=...) | Free |
| Telegram | connect_telegram(bot_token=...) | Free |
| Discord | install_discord(display_name=...) | Free |
| Slack | install_slack(display_name=...) | Free |
| X/Twitter | OAuth or own tokens | Paid |
| SMS | own Twilio/Telnyx number | BYO |
| Bluesky | own handle + app password | Free |

WhatsApp, iMessage, Instagram, Facebook, voice are not live on the hosted gateway. Don't try them.

### Useful SDK features

- client.behavior_prompt() → per-channel etiquette for your system prompt
- message.typing() → keep typing indicator alive during long LLM calls
- client.listen(ack="...") → instant acknowledgement on channels without typing
- client.send_message(conversation_id, text) → proactive messages
- Rich blocks (cards, buttons) for Telegram

### Verify it works

```bash
# Send a test email
curl -s -X POST https://api.trycaspianai.com/v1/test-emails \
  -H "Authorization: Bearer $CASPIAN_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"text":"hello, are you alive?"}'

# Check events
curl -s "https://api.trycaspianai.com/v1/events?type=message.sent" \
  -H "Authorization: Bearer $CASPIAN_API_KEY"
```

### Links

- SDK repo: https://github.com/TryCaspian/caspian-sdk
- Integration guide: https://api.trycaspianai.com/SKILL.md
- Docs: https://www.trycaspianai.com/docs/
- REST reference: https://api.trycaspianai.com/docs
