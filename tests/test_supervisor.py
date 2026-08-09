"""Tests for the Supervisor (async orchestration + fan-out timing)."""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from policydecoder.agents.extractor_agent import ExtractorAgent
from policydecoder.agents.researcher_agent import ResearcherAgent
from policydecoder.supervisor import Supervisor


class TestLifeCalc:
    def test_full_life_calc(self):
        """Life calc computes XIRR + term+SIP + surrender from the data."""
        data = {
            "policy_name": "LIC Jeevan Anand",
            "annual_premium": 50000,
            "premium_term_years": 15,
            "policy_term_years": 15,
            "sum_assured": 1000000,
            "maturity_value_at_8pct": 1120000,
            "policy_start_date": "2022-01-01",
            "free_look_period_days": 15,
        }
        calc = Supervisor._life_calc(data, user_age=30)
        assert calc["xirr"] > 0
        assert calc["term_sip_value"] > calc["policy_maturity"]  # SIP beats policy
        assert calc["premiums_paid"] > 0
        assert calc["surrender_loss"] >= 0

    def test_incomplete_life_data_returns_zeros(self):
        """Missing premium/term/maturity → safe zeros, no crash."""
        calc = Supervisor._life_calc({"policy_name": "X"}, user_age=30)
        assert calc["xirr"] == 0.0
        assert calc["free_look_days"] == 15


class TestDraftLetter:
    @pytest.mark.asyncio
    async def test_draft_letter_with_drafter(self):
        """Supervisor delegates letter drafting to the LetterDrafter."""
        supervisor = _make_supervisor(router_label="HEALTH")
        mock_drafter = MagicMock()
        mock_drafter.run = _fake_letter
        supervisor.letter_drafter = mock_drafter

        letter = await supervisor.draft_letter(
            letter_type="complaint",
            policy_data={"policy_name": "X", "insurer": "LIC"},
            analysis={"summary": "bad"},
        )
        assert "complaint" in letter

    @pytest.mark.asyncio
    async def test_draft_letter_no_drafter_returns_empty(self):
        supervisor = _make_supervisor(router_label="HEALTH")
        supervisor.letter_drafter = None
        letter = await supervisor.draft_letter("complaint", {}, {})
        assert letter == ""


async def _fake_letter(letter_type, policy_data, analysis, **kw):
    return f"drafted {letter_type} letter"


class TestSupervisorFanOut:
    @pytest.mark.asyncio
    async def test_health_media_runs_full_pipeline(self):
        """Health media → Router → gather(Extractor, Researcher) → Health Analyst."""
        supervisor = _make_supervisor(router_label="HEALTH")
        result = await supervisor.process_media(media_urls=["u1"])
        # Health path returns data + analysis (+ findings)
        assert "data" in result
        assert "analysis" in result
        assert result["analysis"]["verdict"] == "GOOD"

    @pytest.mark.asyncio
    async def test_async_fanout_timing(self):
        """Researcher (2s) and Extractor (3s) must run in parallel (~3s, not 5s)."""
        supervisor = _make_supervisor(router_label="HEALTH")

        async def slow_researcher(topic, **kw):
            await asyncio.sleep(2)
            return [{"source": "https://joinditto.in/a", "claim": "c", "url": "u"}]

        async def slow_extractor(media_urls, document_type="HEALTH", **kw):
            await asyncio.sleep(3)
            return {
                "data": {"sum_insured": 1500000, "annual_premium": 18000},
                "missing": [],
                "short_circuited": False,
            }

        supervisor.researcher.run = slow_researcher
        supervisor.extractor.run = slow_extractor

        start = time.monotonic()
        await supervisor.process_media(media_urls=["u1"])
        elapsed = time.monotonic() - start

        # 3s if parallel; ~5s if sequential
        assert elapsed < 4.5, f"agents did not run in parallel (took {elapsed:.1f}s)"

    @pytest.mark.asyncio
    async def test_text_question_routes_to_question(self):
        """A text question doesn't need extraction/research — just a reply."""
        supervisor = _make_supervisor(router_label=None)
        result = await supervisor.process_text("What is a room rent cap?")
        assert result

    @pytest.mark.asyncio
    async def test_correlation_id_and_trace_started(self):
        """The supervisor sets correlation ID + starts an Opik trace."""
        supervisor = _make_supervisor(router_label="HEALTH")
        with (
            patch("policydecoder.supervisor.start_trace") as mock_start_trace,
            patch("policydecoder.supervisor.set_correlation_id") as mock_set_cid,
        ):
            await supervisor.process_media(media_urls=["u1"], conversation_id="conv-1")
            mock_set_cid.assert_called_once_with("conv-1")
            mock_start_trace.assert_called_once()


def _make_supervisor(router_label="HEALTH"):
    """Build a Supervisor with stubbed agents."""
    llm = MagicMock()

    class FakeRouter:
        async def run(self, media_urls, input_path=None):
            return (router_label, 0.95)

    extractor = MagicMock()
    extractor.extract_health.return_value = {
        "policy_name": "Care Supreme",
        "sum_insured": 1500000,
        "annual_premium": 18000,
    }
    extractor_agent = ExtractorAgent(extractor=extractor, llm_client=llm, model="fake")
    extractor_agent.run = _fast_extractor

    researcher = ResearcherAgent(llm_client=llm, model="fake")
    researcher.run = _fast_researcher

    analyst_resp = MagicMock()
    analyst_resp.choices[0].message.content = '{"verdict": "GOOD", "summary": "ok"}'
    analyst_llm = MagicMock()
    analyst_llm.chat.completions.create.return_value = analyst_resp
    from policydecoder.agents.health_analyst import HealthAnalyst

    analyst = HealthAnalyst(llm_client=analyst_llm, model="fake", benchmark_lookup=lambda n: None)
    analyst.run = _fast_analyst

    return Supervisor(
        router=FakeRouter(),
        extractor=extractor_agent,
        researcher=researcher,
        health_analyst=analyst,
        life_analyst=None,
        letter_drafter=None,
    )


async def _fast_extractor(media_urls, document_type="HEALTH", **kw):
    return {
        "data": {"policy_name": "Care Supreme", "sum_insured": 1500000, "annual_premium": 18000},
        "missing": [],
        "short_circuited": False,
    }


async def _fast_researcher(topic, **kw):
    return [{"source": "https://joinditto.in/a", "claim": "c", "url": "u"}]


async def _fast_analyst(extraction, findings, **kw):
    return {"verdict": "GOOD", "summary": "ok"}
