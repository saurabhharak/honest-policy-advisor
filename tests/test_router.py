"""Tests for the document router (classifier)."""

from unittest.mock import MagicMock

from policydecoder.router import (
    DEFAULT_LABEL,
    classify_document,
    heuristic_classify,
)


class TestHeuristicClassify:
    def test_health_keywords(self):
        text = (
            "This policy covers room rent, co-pay, waiting period for "
            "pre-existing diseases, and hospital exclusions."
        )
        assert heuristic_classify(text) == "HEALTH"

    def test_life_keywords(self):
        text = (
            "The surrender value table shows the benefit illustration "
            "with maturity value and premium allocation charge."
        )
        assert heuristic_classify(text) == "LIFE"

    def test_term_keywords(self):
        text = "Term insurance plan with death benefit only, no maturity value."
        assert heuristic_classify(text) == "TERM"

    def test_empty_text_returns_unknown(self):
        """The raw heuristic returns UNKNOWN for empty input."""
        assert heuristic_classify("") == "UNKNOWN"

    def test_garbage_text_returns_unknown(self):
        assert heuristic_classify("asdkjfh qwiueyr qweiu") == "UNKNOWN"

    def test_health_outranks_life_when_both_present(self):
        """A document mentioning both should be health if health terms dominate."""
        text = (
            "Health insurance policy with room rent cap and co-pay. "
            "Also mentions surrender value in the fine print."
        )
        assert heuristic_classify(text) == "HEALTH"


class TestClassifyDocument:
    def test_uses_llm_when_available(self):
        """When the LLM returns a clean classification, use it."""
        fake_llm = MagicMock()
        fake_llm.chat.completions.create.return_value = _response(
            '{"document_type": "HEALTH", "confidence": 0.95}'
        )
        label, confidence = classify_document(
            fake_llm, ["https://example.com/page1.jpg"], model="fake-model"
        )
        assert label == "HEALTH"
        assert confidence == 0.95

    def test_falls_back_to_heuristic_on_llm_failure(self):
        """If the LLM call raises, use deterministic keyword scoring."""
        fake_llm = MagicMock()
        fake_llm.chat.completions.create.side_effect = Exception("boom")
        label, confidence = classify_document(
            fake_llm,
            ["https://example.com/health.jpg"],
            model="fake-model",
            fallback_text="This covers room rent and co-pay for pre-existing diseases.",
        )
        assert label == "HEALTH"

    def test_falls_back_to_heuristic_on_garbage_response(self):
        """If the LLM returns unparseable JSON, use deterministic scoring."""
        fake_llm = MagicMock()
        fake_llm.chat.completions.create.return_value = _response("not json at all")
        label, confidence = classify_document(
            fake_llm,
            ["https://example.com/life.jpg"],
            model="fake-model",
            fallback_text="surrender value benefit illustration maturity",
        )
        assert label == "LIFE"

    def test_low_confidence_uses_heuristic(self):
        """Low-confidence LLM answers defer to the deterministic path."""
        fake_llm = MagicMock()
        fake_llm.chat.completions.create.return_value = _response(
            '{"document_type": "HEALTH", "confidence": 0.2}'
        )
        label, _ = classify_document(
            fake_llm,
            ["https://example.com/life.jpg"],
            model="fake-model",
            fallback_text="surrender value maturity benefit",
        )
        assert label == "LIFE"

    def test_defaults_to_life_on_totally_unknown(self):
        """Even the heuristic can't classify → default to LIFE (backwards-compat)."""
        fake_llm = MagicMock()
        fake_llm.chat.completions.create.side_effect = Exception("boom")
        label, _ = classify_document(
            fake_llm,
            ["https://example.com/blurry.jpg"],
            model="fake-model",
            fallback_text="",
        )
        assert label == DEFAULT_LABEL


def _response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices[0].message.content = content
    return resp
