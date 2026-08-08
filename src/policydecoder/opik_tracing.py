"""Opik tracing wrapper — production LLM observability.

Wraps the app's LLM call sites so every extraction, analysis, letter,
router classification, and guardrail check is traced with inputs,
outputs, and latency. Lazily imports Opik; when OPIK_ENABLED is unset
every function is a no-op with zero latency and Opik is never imported.

The 4 LLM choke points instrumented are: extractor (vision), analyzer
(_generate), router (classify), guardrails (rail check).
"""

from collections.abc import Callable
from typing import Any

from policydecoder.config import get_config
from policydecoder.logging import get_correlation_id, get_logger

logger = get_logger("policydecoder.opik")


def is_enabled() -> bool:
    """Whether Opik tracing is active (OPIK_ENABLED=true)."""
    return get_config().opik_enabled


def trace_llm(
    name: str,
    *,
    model: str,
    input_text: str,
    output_text: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record one LLM call as an Opik trace/span. No-op when disabled."""
    if not is_enabled():
        return
    try:
        _track(
            name,
            model=model,
            input_text=input_text,
            output_text=output_text,
            metadata=metadata or {},
        )
    except Exception as e:  # tracing must never break the app
        logger.warning("Opik trace failed for %s: %s", name, e)


def _track(
    name: str,
    *,
    model: str,
    input_text: str,
    output_text: str,
    metadata: dict[str, Any],
) -> None:
    """Actual Opik call. Imported lazily; called only when enabled."""
    meta = dict(metadata)
    meta.setdefault("model", model)
    meta.setdefault("correlation_id", get_correlation_id())

    client = _get_client()
    with client.span(
        name=name,
        type="llm",
        input={"input": input_text},
        output={"output": output_text},
        metadata=meta,
        tags=["policydecoder"],
    ):
        pass


_CLIENT = None


def _get_client():
    """Lazily build the Opik client. Called only when enabled."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    import opik

    config = get_config()
    _CLIENT = opik.Opik(
        project_name="policy-decoder",
        host=config.opik_url or None,
        api_key=config.opik_api_key or None,
    )
    return _CLIENT


def track_call(name: str) -> Callable:
    """Decorator form: wraps a function and traces it. No-op when disabled."""

    def decorator(fn: Callable) -> Callable:
        if not is_enabled():
            return fn
        try:
            from opik import track

            return track(name=name, type="llm", tags=["policydecoder"])(fn)
        except Exception as e:
            logger.warning("Opik decorator failed for %s: %s", name, e)
            return fn

    return decorator


def flush() -> None:
    """Flush pending traces. No-op when disabled or Opik not installed."""
    if not is_enabled():
        return
    try:
        if _CLIENT is not None:
            _CLIENT.flush()
    except Exception as e:
        logger.warning("Opik flush failed: %s", e)


def set_trace_metadata(correlation_id: str, channel: str) -> None:
    """Attach correlation ID + channel to the current trace context."""
    if not is_enabled():
        return
    try:
        from opik.opik_context import update_current_trace

        update_current_trace(
            name="policy_message",
            metadata={"correlation_id": correlation_id, "channel": channel},
        )
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Opik set_trace_metadata failed: %s", e)
