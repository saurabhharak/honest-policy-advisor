"""Tests for the message handler."""

from unittest.mock import MagicMock

from policydecoder.case_manager import CaseState, case_manager
from policydecoder.handler import handle
from tests.conftest import FakeAnalyzer, FakeExtractor, FakeMessage


def _make_client():
    return MagicMock()


class TestIdleState:
    def test_new_policy_prompts_for_photo(self):
        client = _make_client()
        msg = FakeMessage(text="Can you check my LIC policy?")
        extractor = FakeExtractor()
        analyzer = FakeAnalyzer()

        handle(client, msg, extractor, analyzer)

        assert len(msg.replies) == 1
        assert "photo" in msg.replies[0].lower() or "pdf" in msg.replies[0].lower()

    def test_question_gets_welcome(self):
        client = _make_client()
        msg = FakeMessage(text="What is a ULIP?")
        extractor = FakeExtractor()
        analyzer = FakeAnalyzer()

        handle(client, msg, extractor, analyzer)

        assert len(msg.replies) >= 1

    def test_empty_message(self):
        client = _make_client()
        msg = FakeMessage(text="")
        extractor = FakeExtractor()
        analyzer = FakeAnalyzer()

        handle(client, msg, extractor, analyzer)

        assert len(msg.replies) == 1


class TestMediaHandling:
    def test_photo_extracts_policy_data(self):
        client = _make_client()
        msg = FakeMessage(
            text="",
            media=[{"url": "https://example.com/policy_photo.jpg"}],
        )
        extractor = FakeExtractor()
        analyzer = FakeAnalyzer()

        handle(client, msg, extractor, analyzer)

        assert len(msg.replies) >= 1
        reply = msg.replies[0]
        assert "LIC Jeevan Anand" in reply
        assert "50,000" in reply

    def test_photo_asks_for_age(self):
        client = _make_client()
        msg = FakeMessage(
            text="",
            media=[{"url": "https://example.com/policy.jpg"}],
        )
        extractor = FakeExtractor()
        analyzer = FakeAnalyzer()

        handle(client, msg, extractor, analyzer)

        reply = msg.replies[0]
        assert "age" in reply.lower() or "old" in reply.lower()

    def test_unreadable_photo(self):
        client = _make_client()
        msg = FakeMessage(
            text="",
            media=[{"url": "https://example.com/blurry.jpg"}],
        )
        extractor = FakeExtractor(canned_data={})
        analyzer = FakeAnalyzer()

        handle(client, msg, extractor, analyzer)

        assert "couldn't read" in msg.replies[0].lower()


class TestAgeAndAnalysis:
    def test_age_triggers_analysis(self):
        client = _make_client()
        extractor = FakeExtractor()
        analyzer = FakeAnalyzer()

        # First: send policy photo
        msg1 = FakeMessage(
            text="",
            media=[{"url": "https://example.com/policy.jpg"}],
        )
        handle(client, msg1, extractor, analyzer)

        # Then: provide age
        msg2 = FakeMessage(text="32")
        handle(client, msg2, extractor, analyzer)

        # Should get the analysis report
        assert len(msg2.replies) >= 1
        reply = msg2.replies[0]
        assert "XIRR" in reply or "return" in reply.lower()

    def test_non_numeric_reply(self):
        client = _make_client()
        extractor = FakeExtractor()
        analyzer = FakeAnalyzer()

        # Send policy photo
        msg1 = FakeMessage(
            text="",
            media=[{"url": "https://example.com/policy.jpg"}],
        )
        handle(client, msg1, extractor, analyzer)

        # Send non-numeric response
        msg2 = FakeMessage(text="I don't want to share my age")
        analyzer2 = FakeAnalyzer()
        # Force it to return UNKNOWN for non-numeric
        handle(client, msg2, extractor, analyzer2)


class TestConfirmFlow:
    def test_confirm_after_analysis_drafts_letter(self):
        client = _make_client()
        extractor = FakeExtractor()
        analyzer = FakeAnalyzer()

        # Full flow: photo → age → confirm
        msg1 = FakeMessage(
            text="",
            media=[{"url": "https://example.com/policy.jpg"}],
        )
        handle(client, msg1, extractor, analyzer)

        msg2 = FakeMessage(text="30")
        handle(client, msg2, extractor, analyzer)

        msg3 = FakeMessage(text="Yes, draft the letter")
        handle(client, msg3, extractor, analyzer)

        # Should have the letter
        assert len(msg3.replies) >= 1
        reply = msg3.replies[0]
        assert "letter" in reply.lower() or "complaint" in reply.lower() or "gmail" in reply.lower()


class TestStatusCheck:
    def test_status_returns_timeline(self):
        client = _make_client()
        extractor = FakeExtractor()
        analyzer = FakeAnalyzer()

        # Create a case first
        msg1 = FakeMessage(
            text="",
            media=[{"url": "https://example.com/policy.jpg"}],
        )
        handle(client, msg1, extractor, analyzer)

        msg2 = FakeMessage(text="status")
        handle(client, msg2, extractor, analyzer)

        assert len(msg2.replies) >= 1
