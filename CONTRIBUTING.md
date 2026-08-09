# Contributing

Thanks for contributing to honest-policy-advisor! This guide covers the workflow and standards for this repo.

## Development setup

```bash
# Install dependencies (including dev tools)
uv sync --all-extras

# Install pre-commit hooks
uv run pre-commit install
```

## Development loop

```bash
# Lint + auto-fix
uv run ruff check src tests scripts --fix

# Format
uv run ruff format src tests scripts

# Type check
uv run mypy src/policydecoder

# Tests
uv run pytest
```

CI runs all four on every push/PR. Make them pass locally first.

## Conventions

- **Tests first.** Write the test before the implementation for any new behavior. `uv run pytest` must be green before committing.
- **The LLM never does math.** All financial computation lives in `calculator.py` / `health_calculator.py`. The LLM only interprets computed numbers and writes prose.
- **The LLM never sends messages.** Only `handler.py` replies via `message.reply()`.
- **No channel branching.** The one `on_message` handler routes automatically; do not add email-vs-Telegram branches.
- **Pure functions for logic.** New scoring/calculation functions take plain numbers and return plain results — no I/O, no LLM calls.
- **One agent, one responsibility.** Specialist agents live in `src/policydecoder/agents/`, extend `BaseAgent`, and never touch each other's concerns. The supervisor orchestrates; agents don't call each other directly.
- **Short-circuit extraction.** The extractor agent never burns retries confirming data is absent — triage short-circuits and returns a missing list.
- **Researcher cites only whitelisted domains** (`irdai.gov.in`, `joinditto.in`, `beshak.org`), enforced at the Python layer.

## Adding a new analysis metric

1. Write tests for the pure function in `tests/test_health_calculator.py` (or `test_calculator.py` for life).
2. Implement it in the corresponding module.
3. Wire it into `score_health_policy` / the supervisor's analyst call.
4. Run the full suite + lint + mypy.

## Adding a new specialist agent

1. Create `src/policydecoder/agents/<name>_agent.py` extending `BaseAgent`.
2. Write its `run()` tests first (mock the LLM — never hit a real model).
3. Wire it into `Supervisor` (add it to `process_media` or fan it out in `asyncio.gather`).
4. Register it in `main.py`'s supervisor construction.

## Insurer benchmark data

`src/policydecoder/data/insurer_metrics.json` is curated from the IRDAI Annual Report. When refreshing:

- Update `as_of` and keep `source_url` on every row.
- Never guess a missing value — use `null`; the scorer reports "no data".

## Committing

- Keep commits focused on one logical change.
- Follow conventional commit prefixes: `feat:`, `fix:`, `chore:`, `docs:`, `ci:`, `test:`.
- Pre-commit hooks (ruff lint/format, uv lock check) run automatically.

## Reporting issues

Include: what you expected, what happened, the policy type (health/life) if relevant, and any error output.
