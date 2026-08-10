"""Structured logging with per-conversation correlation IDs.

Replaces ad-hoc print() calls with module loggers that carry a
correlation ID (set once per incoming message at the handler boundary)
so every log record can be tied back to a specific conversation and to
its Opik trace (see opik_tracing.py).
"""

import logging
from contextvars import ContextVar

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s [cid=%(correlation_id)s] %(message)s"


class SafeFormatter(logging.Formatter):
    """Formatter that tolerates records missing the correlation_id attr.

    Our CorrelationIdFilter sets it on our own loggers, but third-party
    loggers (e.g. opik/httpx) reach the root handler too — those records
    lack the attribute and would otherwise crash formatting.
    """

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = ""
        return super().format(record)


class CorrelationIdFilter(logging.Filter):
    """Injects the current correlation ID into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


def set_correlation_id(cid: str) -> None:
    """Set the correlation ID for the current context (e.g., one message)."""
    _correlation_id.set(cid)


def get_correlation_id() -> str:
    """Return the current correlation ID (empty string if unset)."""
    return _correlation_id.get()


def get_logger(name: str) -> logging.Logger:
    """Return a module logger with the correlation-id filter attached."""
    logger = logging.getLogger(name)
    if not any(isinstance(f, CorrelationIdFilter) for f in logger.filters):
        logger.addFilter(CorrelationIdFilter())
    return logger


_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger handler/formatter once.

    Writes to stderr AND to policydecoder.log in the project root, so
    background runs (whose stdout isn't captured on Windows) are still
    diagnosable.
    """
    global _configured
    if _configured:
        return
    fmt = SafeFormatter(_FORMAT)

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root = logging.getLogger()
    root.addHandler(stream)

    try:
        from pathlib import Path

        file_handler = logging.FileHandler(
            Path(__file__).resolve().parent.parent.parent / "policydecoder.log",
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except Exception:
        pass  # file logging is best-effort: never break startup if the log file is unwritable  # nosec B110

    root.setLevel(level)
    _configured = True
