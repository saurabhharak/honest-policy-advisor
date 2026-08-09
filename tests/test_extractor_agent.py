"""Tests for the Extractor Agent (agentic short-circuit loop)."""

from unittest.mock import MagicMock

import pytest

from policydecoder.agents.extractor_agent import ExtractorAgent


def _make_agent(extraction_result, triage_result=None):
    """Build an ExtractorAgent with mocked vision extraction + triage LLM."""
    extractor = MagicMock()
    if isinstance(extraction_result, list):
        extractor.extract_health.side_effect = extraction_result
        extractor.extract_life.side_effect = extraction_result
    else:
        extractor.extract_health.return_value = extraction_result
        extractor.extract_life.return_value = extraction_result

    llm = MagicMock()
    if triage_result is not None:
        resp = MagicMock()
        resp.choices[0].message.content = triage_result
        llm.chat.completions.create.return_value = resp
    return ExtractorAgent(extractor=extractor, llm_client=llm, model="fake-model")


class TestShortCircuit:
    @pytest.mark.asyncio
    async def test_complete_extraction_no_requery(self):
        """When extraction has all required fields, no triage/requery happens."""
        data = {
            "policy_name": "Care Supreme",
            "insurer": "Care Health",
            "sum_insured": 1500000,
            "annual_premium": 18000,
            "room_rent_cap": "no cap",
            "waiting_periods": {"accident_days": 30},
        }
        agent = _make_agent(data)
        result = await agent.run(media_urls=["u1"], document_type="HEALTH")
        assert result["short_circuited"] is False
        assert result["missing"] == []
        assert result["data"]["sum_insured"] == 1500000
        # Triage LLM must NOT be called when extraction is complete
        agent.llm.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_short_circuits_when_data_absent(self):
        """If the doc genuinely lacks the data, exit early without max retries."""
        partial = {
            "policy_name": "Receipt",
            "insurer": "Care Health",
            "annual_premium": 18000,
            # missing sum_insured, no waiting_periods
        }
        agent = _make_agent(
            partial,
            triage_result='{"data_exists_in_document": false}',
        )
        result = await agent.run(media_urls=["u1"], document_type="HEALTH")
        assert result["short_circuited"] is True
        assert "sum_insured" in result["missing"]
        # extract called once, NOT the max retries
        agent.extractor.extract_health.assert_called_once()

    @pytest.mark.asyncio
    async def test_requeries_once_when_data_may_exist(self):
        """If triage says data may exist, re-query once with targeted prompt."""
        first = {
            "policy_name": "Care Supreme",
            "insurer": "Care Health",
            "annual_premium": 18000,
            "sum_insured": None,
        }
        second = {
            "policy_name": "Care Supreme",
            "insurer": "Care Health",
            "annual_premium": 18000,
            "sum_insured": 1500000,
        }
        agent = _make_agent(
            [first, second],
            triage_result='{"data_exists_in_document": true}',
        )
        result = await agent.run(media_urls=["u1", "u2"], document_type="HEALTH")
        assert result["data"]["sum_insured"] == 1500000
        assert result["short_circuited"] is False

    @pytest.mark.asyncio
    async def test_requery_still_missing_returns_partial(self):
        """After 1 retry the data is still missing → return partial + missing."""
        partial = {
            "policy_name": "Care Supreme",
            "annual_premium": 18000,
            "sum_insured": None,
        }
        agent = _make_agent(
            [partial, partial],
            triage_result='{"data_exists_in_document": true}',
        )
        result = await agent.run(media_urls=["u1", "u2"], document_type="HEALTH")
        assert "sum_insured" in result["missing"]
        assert result["data"]["policy_name"] == "Care Supreme"

    @pytest.mark.asyncio
    async def test_max_one_retry(self):
        """Never more than 1 retry even if triage keeps saying true."""
        partial = {"policy_name": "X"}
        agent = _make_agent(
            [partial, partial, partial, partial],
            triage_result='{"data_exists_in_document": true}',
        )
        await agent.run(media_urls=["u1"], document_type="HEALTH")
        # 1 initial + 1 retry = 2 calls max
        assert agent.extractor.extract_health.call_count <= 2
