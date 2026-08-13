"""Shared config for the eval harness.

Reuses the app's existing env config (OPIK_ENABLED, OPIK_URL, OPENAI_*)
plus an optional EVAL_JUDGE_MODEL override for the LLM judge. Opik is
lazily imported so the harness degrades to deterministic-only mode when
Opik is not reachable/configured.
"""

from typing import Any

from policydecoder.config import get_config

# Default judge model (Featherless, OpenAI-compatible).
DEFAULT_JUDGE_MODEL = "deepseek-ai/DeepSeek-V4-Flash"

# How many dataset items to evaluate per agent by default (cost control).
DEFAULT_NB_SAMPLES = 5

# task_threads: each thread spins its own event loop + clients. Keep low.
DEFAULT_TASK_THREADS = 2

# Datasets all live in this Opik project.
OPIK_PROJECT = "policy-decoder"


def get_judge_model() -> str:
    """The LLM judge model: EVAL_JUDGE_MODEL env override, else the app LLM."""
    import os

    override = os.getenv("EVAL_JUDGE_MODEL", "").strip()
    if override:
        return override
    return get_config().llm_model or DEFAULT_JUDGE_MODEL


def get_opik_client() -> Any:
    """Build the Opik client lazily. Returns None when disabled/unreachable."""
    config = get_config()
    if not config.opik_enabled:
        return None
    try:
        import opik

        return opik.Opik(
            project_name=OPIK_PROJECT,
            host=config.opik_url or None,
            api_key=config.opik_api_key or None,
        )
    except Exception:
        return None
