"""Tests for the Supervisor (async orchestration + fan-out timing)."""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from policydecoder.agents.extractor_agent import ExtractorAgent
from policydecoder.agents.researcher_agent import ResearcherAgent
from policydecoder.supervisor import Supervisor


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
        async def run(self, media_urls):
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
