"""Tests for the Researcher Agent (whitelisted fetch + fact-drift prevention)."""

from unittest.mock import MagicMock, patch

import pytest

from policydecoder.agents.researcher_agent import ALLOWED_DOMAINS, ResearcherAgent, _is_allowed


class TestWhitelist:
    def test_whitelist_domains(self):
        assert "irdai.gov.in" in ALLOWED_DOMAINS
        assert "joinditto.in" in ALLOWED_DOMAINS

    def test_allowed_domain(self):
        assert _is_allowed("https://joinditto.in/articles/how-to-choose-health/") is True
        assert _is_allowed("https://irdai.gov.in/annual-report") is True

    def test_blocked_domain(self):
        assert _is_allowed("https://scam-insurance.com/best-plan") is False
        assert _is_allowed("https://random-blog.example.org/sponsored") is False

    def test_no_url_blocked(self):
        assert _is_allowed("") is False
        assert _is_allowed(None) is False


class TestResearcher:
    def _agent(self, fetch_result=None, fetch_raises=None, summary_text=None):
        llm = MagicMock()
        if summary_text is not None:
            resp = MagicMock()
            resp.choices[0].message.content = summary_text
            llm.chat.completions.create.return_value = resp
        if fetch_result is not None:
            resp = MagicMock()
            resp.text = fetch_result
            fetch_result_obj = resp
        else:
            fetch_result_obj = None
        return ResearcherAgent(
            llm_client=llm,
            model="fake-model",
            fetch_fn=_fake_fetch(fetch_result_obj, fetch_raises),
        )

    @pytest.mark.asyncio
    async def test_picks_url_and_returns_findings(self):
        agent = self._agent(
            fetch_result="Care Health has a 93% claim settlement ratio per IRDAI.",
            summary_text="Care Health reports a 93% claim settlement ratio.",
        )
        findings = await agent.run(topic="care_health_csr")
        assert isinstance(findings, list)
        assert len(findings) >= 1
        assert "claim" in findings[0]
        assert "93%" in findings[0]["claim"]  # LLM summary, not raw HTML
        assert "source" in findings[0]
        assert "url" in findings[0]

    @pytest.mark.asyncio
    async def test_uses_llm_summary_not_raw_text(self):
        """The finding claim is the LLM summary, not the raw fetched page."""
        agent = self._agent(
            fetch_result="<html><body>raw page content</body></html>",
            summary_text="This is the clean LLM summary of the page.",
        )
        findings = await agent.run(topic="care_health_csr")
        assert findings[0]["claim"] == "This is the clean LLM summary of the page."

    @pytest.mark.asyncio
    async def test_whitelist_enforcement(self):
        """Content fetched from a non-whitelisted domain is dropped."""
        agent = self._agent(fetch_result="This scam blog says the best plan is X.")
        # Force the topic to resolve to a non-whitelisted URL
        with patch(
            "policydecoder.agents.researcher_agent.TOPIC_URLS",
            {"bad_topic": ["https://scam-insurance.com/x"]},
        ):
            findings = await agent.run(topic="bad_topic")
        assert findings == []

    @pytest.mark.asyncio
    async def test_fetch_failure_returns_empty(self):
        agent = self._agent(fetch_raises=Exception("network down"))
        findings = await agent.run(topic="care_health_csr")
        assert findings == []

    @pytest.mark.asyncio
    async def test_unknown_topic_returns_empty(self):
        agent = self._agent()
        findings = await agent.run(topic="totally_unknown_topic")
        assert findings == []


def _fake_fetch(result, raises):
    """Return an async fake of the fetch function."""

    async def fetch_fn(url: str):
        if raises:
            raise raises
        return result

    return fetch_fn
