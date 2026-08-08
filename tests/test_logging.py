"""Tests for the structured logging layer."""

import logging

from policydecoder import logging as pd_logging
from policydecoder.logging import (
    CorrelationIdFilter,
    configure_logging,
    get_correlation_id,
    get_logger,
    set_correlation_id,
)


class TestLogger:
    def test_get_logger_has_filter(self):
        logger = get_logger("test.module")
        assert logger.name == "test.module"
        # The correlation-id filter should be attached
        filters = [f for f in logger.filters if isinstance(f, CorrelationIdFilter)]
        assert filters

    def test_logger_is_cached(self):
        a = get_logger("cache.check")
        b = get_logger("cache.check")
        assert a is b


class TestCorrelationId:
    def test_set_and_get(self):
        set_correlation_id("conv-123")
        assert get_correlation_id() == "conv-123"
        # Cleanup so we don't leak into other tests
        set_correlation_id("")

    def test_records_carry_correlation_id(self):
        import io

        set_correlation_id("conv-456")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(pd_logging._FORMAT))
        logger = get_logger("test.corr")
        logger.setLevel(logging.INFO)
        logger.handlers = [handler]
        logger.info("hello")
        set_correlation_id("")
        record_text = stream.getvalue()
        assert "conv-456" in record_text

    def test_no_correlation_id_no_crash(self):
        import io

        set_correlation_id("")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(pd_logging._FORMAT))
        logger = get_logger("test.nocorr")
        logger.setLevel(logging.INFO)
        logger.handlers = [handler]
        logger.info("no id here")  # must not raise
        set_correlation_id("")
        assert "no id here" in stream.getvalue()


class TestConfigureLogging:
    def test_configure_logging_runs(self):
        # Should not raise; callable multiple times
        configure_logging(level=logging.WARNING)
        configure_logging(level=logging.DEBUG)
