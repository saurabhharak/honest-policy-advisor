"""Tests for the Health and Life Analyst agents."""

from unittest.mock import MagicMock, patch

import pytest

from policydecoder.agents.health_analyst import HealthAnalyst
from policydecoder.agents.life_analyst import LifeAnalyst


class TestHealthAnalyst:
    @pytest.mark.asyncio
    async def test_delegates_math_to_calculator(self):
        """The analyst must call score_health_policy, not compute itself."""
        llm = MagicMock()
        resp = MagicMock()
        resp.choices[
            0
        ].message.content = '{"verdict": "GOOD", "summary": "Looks fine.", "red_flags": []}'
        llm.chat.completions.create.return_value = resp

        with patch(
            "policydecoder.agents.health_analyst.score_health_policy",
            return_value={
                "overall": "GOOD",
                "policy_flags": [],
                "insurer_metrics": {"icr_status": "healthy"},
            },
        ) as mock_score:
            analyst = HealthAnalyst(
                llm_client=llm,
                model="fake-model",
                benchmark_lookup=lambda name: {"name": name},
            )
            result = await analyst.run(
                extraction={"policy_name": "Care Supreme", "sum_insured": 1500000},
                findings=[],
            )

        mock_score.assert_called_once()
        assert result["verdict"] == "GOOD"

    @pytest.mark.asyncio
    async def test_incorporates_researcher_findings(self):
        """Whitelisted findings are passed into the analyst prompt."""
        llm = MagicMock()
        resp = MagicMock()
        resp.choices[
            0
        ].message.content = (
            '{"verdict": "REVIEW", "summary": "Check waiting periods.", "red_flags": ["waiting"]}'
        )
        llm.chat.completions.create.return_value = resp

        with patch(
            "policydecoder.agents.health_analyst.score_health_policy",
            return_value={"overall": "REVIEW", "policy_flags": [], "insurer_metrics": {}},
        ):
            analyst = HealthAnalyst(
                llm_client=llm,
                model="fake-model",
                benchmark_lookup=lambda name: None,
            )
            await analyst.run(
                extraction={"policy_name": "X"},
                findings=[{"source": "https://joinditto.in/a", "claim": "c", "url": "u"}],
            )
        # The findings should appear in the LLM user prompt
        prompt = llm.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert "joinditto.in" in prompt


class TestLifeAnalyst:
    @pytest.mark.asyncio
    async def test_verdict_shape(self):
        llm = MagicMock()
        resp = MagicMock()
        resp.choices[
            0
        ].message.content = (
            '{"is_likely_missold": true, "summary": "Low returns.", "key_findings": []}'
        )
        llm.chat.completions.create.return_value = resp

        analyst = LifeAnalyst(llm_client=llm, model="fake-model")
        result = await analyst.run(
            extraction={"policy_name": "LIC Jeevan Anand"},
            calc_results={
                "xirr": 0.038,
                "term_sip_value": 1800000,
                "opportunity_cost": 800000,
            },
            findings=[],
        )
        assert result["is_likely_missold"] is True

    @pytest.mark.asyncio
    async def test_uses_calculated_numbers(self):
        """The analyst's prompt includes the deterministic calc results."""
        llm = MagicMock()
        resp = MagicMock()
        resp.choices[0].message.content = '{"is_likely_missold": false}'
        llm.chat.completions.create.return_value = resp

        analyst = LifeAnalyst(llm_client=llm, model="fake-model")
        await analyst.run(
            extraction={},
            calc_results={"xirr": 0.038, "opportunity_cost": 500000},
            findings=[],
        )
        prompt = llm.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert "0.038" in prompt or "3.8" in prompt
