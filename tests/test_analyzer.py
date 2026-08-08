"""Tests for the analyzer's letter output rail."""

from unittest.mock import MagicMock, patch

from policydecoder import guardrails
from policydecoder.analyzer import PolicyAnalyzer


def _make_analyzer() -> PolicyAnalyzer:
    """A PolicyAnalyzer with a stubbed LLM that returns canned text."""
    llm = MagicMock()
    resp = MagicMock()
    resp.choices[0].message.content = "Dear Sir, please review my claim."
    llm.chat.completions.create.return_value = resp
    return PolicyAnalyzer(llm)


class TestLetterOutputRail:
    def test_complaint_letter_appends_disclaimer_when_enabled(self):
        analyzer = _make_analyzer()
        with patch.object(guardrails, "is_enabled", return_value=True):
            letter = analyzer.draft_complaint_letter(
                policy_name="LIC Jeevan Anand",
                insurer="LIC",
                annual_premium=50000,
                policy_type="endowment",
                purchase_date="2022-01-01",
                xirr=0.038,
                misselling_reasons=["XIRR below 5%"],
            )
        assert "not constitute" in letter.lower()

    def test_complaint_letter_unchanged_when_disabled(self):
        analyzer = _make_analyzer()
        with patch.object(guardrails, "is_enabled", return_value=False):
            letter = analyzer.draft_complaint_letter(
                policy_name="LIC Jeevan Anand",
                insurer="LIC",
                annual_premium=50000,
                policy_type="endowment",
                purchase_date="2022-01-01",
                xirr=0.038,
                misselling_reasons=["XIRR below 5%"],
            )
        assert "not constitute" not in letter.lower()

    def test_free_look_letter_goes_through_rail(self):
        analyzer = _make_analyzer()
        with patch.object(guardrails, "is_enabled", return_value=True):
            letter = analyzer.draft_free_look_letter(
                policy_name="LIC Jeevan Anand",
                insurer="LIC",
                policy_number="12345",
                purchase_date="2026-01-01",
                annual_premium=50000,
                free_look_days=15,
            )
        assert "not constitute" in letter.lower()
