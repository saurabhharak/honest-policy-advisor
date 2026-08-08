"""Tests for the Opik tracing wrapper. Opik itself is never imported."""

from unittest.mock import MagicMock, patch

from policydecoder import opik_tracing
from policydecoder.opik_tracing import (
    flush,
    set_trace_metadata,
    start_trace,
    trace_llm,
)


class TestIsEnabled:
    def test_disabled_by_default_in_tests(self):
        # The autouse opik_off fixture forces tracing off in the test suite
        assert opik_tracing.is_enabled() is False


class TestStartTrace:
    def test_noop_when_disabled(self):
        with patch.object(opik_tracing, "is_enabled", return_value=False):
            start_trace("conv-1", "telegram")  # must not raise
            assert opik_tracing._CURRENT_TRACE_ID is None

    def test_creates_trace_when_enabled(self):
        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_trace.id = "trace-abc"
        mock_client.trace.return_value = mock_trace
        with (
            patch.object(opik_tracing, "is_enabled", return_value=True),
            patch.object(opik_tracing, "_get_client", return_value=mock_client),
        ):
            start_trace("conv-1", "telegram")
            assert opik_tracing._CURRENT_TRACE_ID == "trace-abc"
            mock_client.trace.assert_called_once()
        opik_tracing._CURRENT_TRACE_ID = None


class TestTraceLlm:
    def test_noop_when_disabled(self):
        # is_enabled patched to False
        with patch.object(opik_tracing, "is_enabled", return_value=False):
            # Must not raise and not import opik
            trace_llm(
                "test_call",
                model="model-x",
                input_text="input",
                output_text="output",
                metadata={},
            )
            flush()

    def test_calls_opik_when_enabled(self):
        with (
            patch.object(opik_tracing, "is_enabled", return_value=True),
            patch.object(opik_tracing, "_track") as mock_track,
        ):
            trace_llm(
                "test_call",
                model="model-x",
                input_text="the input",
                output_text="the output",
                metadata={"k": "v"},
            )
            mock_track.assert_called_once()
            args, kwargs = mock_track.call_args
            assert args[0] == "test_call"
            assert kwargs.get("model") == "model-x"

    def test_span_gets_trace_id_when_trace_active(self):
        mock_client = MagicMock()
        opik_tracing._CURRENT_TRACE_ID = "trace-xyz"
        with (
            patch.object(opik_tracing, "is_enabled", return_value=True),
            patch.object(opik_tracing, "_get_client", return_value=mock_client),
        ):
            trace_llm(
                "test_call",
                model="model-x",
                input_text="input",
                output_text="output",
                metadata={},
            )
            span_kwargs = mock_client.span.call_args.kwargs
            assert span_kwargs["trace_id"] == "trace-xyz"
        opik_tracing._CURRENT_TRACE_ID = None


class TestFlush:
    def test_flush_noop_when_disabled(self):
        with patch.object(opik_tracing, "is_enabled", return_value=False):
            flush()  # must not raise


class TestSetTraceMetadata:
    def test_noop_when_disabled(self):
        with patch.object(opik_tracing, "is_enabled", return_value=False):
            set_trace_metadata("conv-1", "telegram")  # must not raise


class TestTrackCallDecorator:
    def test_decorator_preserves_result_when_disabled(self):
        with patch.object(opik_tracing, "is_enabled", return_value=False):
            result = opik_tracing.track_call("test.func")(lambda: 42)()
            assert result == 42
