"""Tests for the Opik tracing wrapper. Opik itself is never imported."""

from unittest.mock import patch

from policydecoder import opik_tracing
from policydecoder.opik_tracing import flush, is_enabled, set_trace_metadata, trace_llm


class TestIsEnabled:
    def test_disabled_by_default(self):
        assert is_enabled() is False


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
