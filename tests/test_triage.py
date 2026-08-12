"""Tests for the dual-track page triage: Pydantic validation, accumulation,
targeted re-read, and the two review-fix guards (cross-page tables + no query storm).
"""

import pytest

from policydecoder.graph.rubrics import load_rubric_file
from policydecoder.graph.triage import accumulate, has_required, prepare_triage
from policydecoder.schemas import LaymanVerdict, PageTriageOutput, TableAnalysisOutput


class TestPydanticValidation:
    def test_page_triage_output_valid(self):
        out = PageTriageOutput.model_validate(
            {
                "page_number": 3,
                "fields": {"annual_premium": 50000},
                "findings": [
                    {
                        "category": "co_pay",
                        "severity": "warning",
                        "what": "Co-pay 30%",
                        "why_concerning": "you pay 30% of every claim",
                        "source_text": "co-pay 30%",
                        "page": 3,
                    }
                ],
                "page_summary": "Premium schedule",
            }
        )
        assert out.page_number == 3
        assert out.fields["annual_premium"] == 50000
        assert out.findings[0].severity == "warning"

    def test_page_triage_output_invalid_severity_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PageTriageOutput.model_validate(
                {"page_number": 1, "findings": [{"category": "x", "severity": "bogus"}]}
            )

    def test_table_analysis_output_valid(self):
        out = TableAnalysisOutput.model_validate(
            {
                "fields": {"surrender_value_table": "Year 1-20 schedule"},
                "findings": [],
                "table_summary": "Full surrender schedule",
            }
        )
        assert "surrender_value_table" in out.fields

    def test_layman_verdict_valid(self):
        v = LaymanVerdict.model_validate(
            {
                "summary": "Policy is fine",
                "items": [
                    {
                        "severity": "info",
                        "what": "No co-pay",
                        "why_it_matters": "you pay no share of claims",
                        "what_to_do": "nothing",
                        "page": 2,
                    }
                ],
                "verdict": "GOOD",
            }
        )
        assert v.verdict == "GOOD"


class TestAccumulate:
    def test_merges_tracks_first_non_null(self):
        state = {
            "page_outputs": [
                {
                    "page_number": 1,
                    "fields": {"policy_name": "X", "annual_premium": None},
                    "findings": [],
                    "page_summary": "",
                },
                {
                    "page_number": 2,
                    "fields": {"annual_premium": 50000},
                    "findings": [],
                    "page_summary": "",
                },
            ],
            "table_output": {
                "fields": {"policy_name": "SHOULD_NOT_OVERRIDE", "sum_assured": 1000000},
                "findings": [],
                "table_summary": "",
            },
            "findings": [],
        }
        out = accumulate(state, None)
        # first-non-null: policy_name from page 1 (page track wins over table),
        # annual_premium from page 2, sum_assured only from table track
        assert out["extraction"]["policy_name"] == "X"
        assert out["extraction"]["annual_premium"] == 50000
        assert out["extraction"]["sum_assured"] == 1000000

    def test_merges_findings_from_both_tracks(self):
        state = {
            "page_outputs": [
                {
                    "page_number": 1,
                    "fields": {},
                    "findings": [{"category": "a", "page": 1}],
                    "page_summary": "",
                }
            ],
            "table_output": {
                "fields": {},
                "findings": [{"category": "b", "page": 14}],
                "table_summary": "",
            },
            "findings": [{"category": "pre", "page": 0}],
        }
        out = accumulate(state, None)
        cats = {f["category"] for f in out["findings"]}
        assert cats == {"a", "b", "pre"}


class TestHasRequired:
    def test_all_required_present(self):
        state = {
            "rubric": {"required_fields": ["sum_insured", "annual_premium"]},
            "extraction": {"sum_insured": 1000000, "annual_premium": 50000},
        }
        assert has_required(state) == "deterministic_calc"

    def test_missing_required_triggers_re_read(self):
        state = {
            "rubric": {"required_fields": ["sum_insured", "annual_premium"]},
            "extraction": {"sum_insured": 1000000},
        }
        assert has_required(state) == "targeted_re_read"


@pytest.mark.asyncio
async def test_prepare_triage_loads_rubric_once():
    """prepare_triage loads the rubric into state; triage nodes read state (no per-page queries)."""

    class FakeStore:
        """Records every store read."""

        def __init__(self):
            self.reads = 0

        async def aget(self, ns, key):
            self.reads += 1
            if key == "rubric":
                return type("Item", (), {"value": load_rubric_file("LIFE")})()
            return None

    from policydecoder.graph.state import AgentContext, GraphContext

    store = FakeStore()
    agents = AgentContext(
        router=None,
        extractor_agent=None,
        researcher=None,
        health_analyst=None,
        life_analyst=None,
        letter_drafter=None,
        analyzer=None,
        llm=None,
    )
    runtime = type(
        "RT",
        (),
        {
            "store": store,
            "context": GraphContext(user_id="u", contact="c", channel="x", agents=agents),
        },
    )()

    state = {"document_type": "LIFE"}
    out = await prepare_triage(state, runtime)
    assert out["rubric"]["product"] == "LIFE"
    assert store.reads == 1  # exactly ONE store read for the rubric (no storm)
