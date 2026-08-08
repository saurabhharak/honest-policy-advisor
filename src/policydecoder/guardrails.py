"""NeMo Guardrails facade — protects the LLM boundary.

Two untrusted-input surfaces reach LLM prompts in this app:
1. User message text (handler.py -> classify_intent)
2. Extracted policy-document fields (handler.py -> analyze_*)

The facade exposes three operations:

- validate_user_input(text): jailbreak / prompt-injection check on user
  message text. Raises GuardrailValidationError on block.
- validate_policy_fields(data): targeted check on high-risk extracted
  free-text fields only (never the full JSON blob — that would blow the
  context window and add seconds of latency). Raises on block.
- validate_letter_output(letter_text): deterministic natural-language
  output rail — appends a disclaimer and sanitizes overpromising claim
  language. No NeMo LLM call.

JSON-returning analyzer calls (classify_intent, analyze_policy, ...) are
NOT routed through NeMo — their shape is enforced by Pydantic schemas in
schemas.py. NeMo is reserved for text-in / text-out boundaries only.

Rails are opt-in via GUARDRAILS_ENABLED. When disabled, every function is
a pure pass-through with zero latency and NeMo is never imported.
"""

import asyncio
from typing import Any

from policydecoder.config import get_config

# High-risk free-text fields extracted from policy documents. These are the
# fields where an attacker could embed instructions that survive extraction.
_HIGH_RISK_FIELDS = (
    "surrender_value_table",
    "charges",
    "exclusions",
    "sub_limits",
    "room_rent_cap",
    "special_conditions",
    "agent_notes",
    "custom_clauses",
)

_MAX_SAMPLE_CHARS = 2_000

_OVERPROMISE_PATTERNS = {
    "guarantee 100% refund": "request a review of the refund as per IRDAI norms",
    "guaranteed payout": "request confirmation of the payout terms",
    "100% claim approval": "request a clear explanation of the claim process",
}

_DISCLAIMER = (
    "\n\n*Disclaimer: This draft is for informational purposes and does not "
    "constitute formal legal or financial advice.*"
)


class GuardrailValidationError(Exception):
    """Raised when an input rail flags malicious or out-of-bounds content."""

    def __init__(self, reason: str, user_message: str):
        self.reason = reason
        self.user_message = user_message
        super().__init__(reason)


def is_enabled() -> bool:
    """Whether rails are active (GUARDRAILS_ENABLED=true)."""
    return get_config().guardrails_enabled


def validate_user_input(text: str) -> None:
    """Jailbreak / prompt-injection check on raw user message text.

    Raises GuardrailValidationError on block. No-op when disabled.
    """
    if not is_enabled():
        return
    result = _generate_rails_check(text, "user_message")
    if result.get("metadata", {}).get("action") == "block":
        raise GuardrailValidationError(
            reason="User prompt injection detected",
            user_message=(
                "I can't process that request — it looks like it's trying to "
                "change how I work. Please ask about your insurance in a "
                "normal way."
            ),
        )


def validate_policy_fields(data: dict[str, Any]) -> None:
    """Targeted injection check on high-risk extracted policy fields only.

    Pulls only the free-text fields most likely to carry injected
    instructions, joins them into a capped ~2000-char sample, and runs the
    injection rail. Never passes the full extracted JSON to NeMo.

    Raises GuardrailValidationError on block. No-op when disabled.
    """
    if not is_enabled():
        return

    suspicious: list[str] = []
    for key in _HIGH_RISK_FIELDS:
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            value = "\n".join(str(v) for v in value)
        if isinstance(value, (str, int, float)):
            suspicious.append(f"{key}: {value}")

    if not suspicious:
        return

    sample = "\n".join(suspicious)[:_MAX_SAMPLE_CHARS]
    result = _generate_rails_check(sample, "policy_document")
    if result.get("metadata", {}).get("action") == "block":
        raise GuardrailValidationError(
            reason="Policy document injection detected",
            user_message=(
                "I found text in this policy document that looks like it's "
                "trying to manipulate my analysis. Please share a clean copy "
                "of the policy."
            ),
        )


def validate_letter_output(letter_text: str) -> str:
    """Deterministic natural-language output rail for drafted letters.

    Appends a disclaimer and sanitizes overpromising claim language.
    No NeMo LLM call. No-op (pass-through) when disabled.
    """
    if not is_enabled():
        return letter_text

    lowered = letter_text.lower()
    for pattern, replacement in _OVERPROMISE_PATTERNS.items():
        if pattern in lowered:
            letter_text = letter_text.replace(pattern, replacement)

    if _DISCLAIMER not in letter_text:
        letter_text += _DISCLAIMER
    return letter_text


# ---------------------------------------------------------------------------
# Async-safe internals
# ---------------------------------------------------------------------------


def _run_async(coro) -> Any:
    """Run a coroutine. Uses asyncio.run() when no loop is running.

    Raises a clear error if called from inside a running loop — callers in
    async frameworks must use the *_async variants instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError(
        "A running event loop was detected. Use validate_user_input_async / "
        "validate_policy_fields_async from async code."
    )


async def validate_user_input_async(text: str) -> None:
    """Async variant of validate_user_input for async frameworks."""
    if not is_enabled():
        return
    result = await _generate_rails_check_async(text, "user_message")
    if result.get("metadata", {}).get("action") == "block":
        raise GuardrailValidationError(
            reason="User prompt injection detected",
            user_message=(
                "I can't process that request — it looks like it's trying to "
                "change how I work. Please ask about your insurance in a "
                "normal way."
            ),
        )


async def validate_policy_fields_async(data: dict[str, Any]) -> None:
    """Async variant of validate_policy_fields for async frameworks."""
    if not is_enabled():
        return

    suspicious: list[str] = []
    for key in _HIGH_RISK_FIELDS:
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            value = "\n".join(str(v) for v in value)
        if isinstance(value, (str, int, float)):
            suspicious.append(f"{key}: {value}")

    if not suspicious:
        return

    sample = "\n".join(suspicious)[:_MAX_SAMPLE_CHARS]
    result = await _generate_rails_check_async(sample, "policy_document")
    if result.get("metadata", {}).get("action") == "block":
        raise GuardrailValidationError(
            reason="Policy document injection detected",
            user_message=(
                "I found text in this policy document that looks like it's "
                "trying to manipulate my analysis. Please share a clean copy "
                "of the policy."
            ),
        )


# ---------------------------------------------------------------------------
# NeMo glue (lazy import — NeMo is an optional dependency)
# ---------------------------------------------------------------------------

_RAILS = None


def _get_rails():
    """Build the LLMRails instance lazily. NeMo imported only when enabled."""
    global _RAILS
    if _RAILS is not None:
        return _RAILS

    try:
        from nemoguardrails import LLMRails
    except ImportError as e:
        raise RuntimeError(
            "GUARDRAILS_ENABLED=true but nemoguardrails is not installed. "
            "Install with: uv sync --extra guardrails"
        ) from e

    from policydecoder.guardrails_config import build_rails_config

    _RAILS = LLMRails(config=build_rails_config())
    return _RAILS


def _generate_rails_check(text: str, context: str) -> dict[str, Any]:
    """Synchronous NeMo generation wrapper (handles the event-loop case)."""
    rails = _get_rails()
    if hasattr(rails, "generate"):
        return rails.generate(messages=[{"role": "user", "content": text}])
    # Fallback for async-only APIs
    return _run_async(rails.generate_async(messages=[{"role": "user", "content": text}]))


async def _generate_rails_check_async(text: str, context: str) -> dict[str, Any]:
    """Async NeMo generation wrapper."""
    rails = _get_rails()
    return await rails.generate_async(messages=[{"role": "user", "content": text}])
