"""Unit tests for eval metrics. No network, no Opik client."""

import json

from policydecoder.evals.data import GOLD_FILES
from policydecoder.evals.metrics import (
    ConfidenceGate,
    HasFindings,
    NormalizedFieldAccuracy,
    RequiredFieldsPresent,
    RobustLLMJudge,
    ShortCircuitCorrectness,
    WhitelistEnforcement,
    XirrConsistency,
    normalize_val,
)


class FakeJudgeLLM:
    """Mimics BaseAgent.generate() returning canned judge JSON."""

    def __init__(self, payload: str):
        self.payload = payload
        self.last_prompt = None

    def generate(self, system, user, timeout=15.0):
        self.last_prompt = user
        return self.payload


class TestNormalize:
    def test_currency_and_commas(self):
        assert normalize_val("₹1,00,000") == 100000.0
        assert normalize_val("1,500,000") == 1500000.0
        assert normalize_val(100000) == 100000.0

    def test_insurer_alias(self):
        assert normalize_val("HDFC ERGO General Insurance") == normalize_val("HDFC ERGO")

    def test_whitespace_case(self):
        assert normalize_val("  Care Supreme  ") == "care supreme"


class TestNormalizedFieldAccuracy:
    def test_perfect_match(self):
        m = NormalizedFieldAccuracy()
        res = m.score(
            output={"sum_insured": 1500000, "annual_premium": 18000},
            reference={"sum_insured": 1500000, "annual_premium": 18000},
        )
        assert res.value == 1.0

    def test_currency_string_vs_number(self):
        m = NormalizedFieldAccuracy()
        res = m.score(
            output={"sum_insured": "₹1,50,000"},
            reference={"sum_insured": 150000},
        )
        assert res.value == 1.0

    def test_insurer_alias_match(self):
        m = NormalizedFieldAccuracy()
        res = m.score(
            output={"insurer": "HDFC ERGO"},
            reference={"insurer": "HDFC ERGO General Insurance"},
        )
        assert res.value == 1.0

    def test_numeric_tolerance(self):
        m = NormalizedFieldAccuracy(tolerance=0.01)
        # 1500000 vs 1510000 = 0.67% off → within 1%
        res = m.score(output={"sum_insured": 1510000}, reference={"sum_insured": 1500000})
        assert res.value == 1.0
        # 1500000 vs 1600000 = 6.7% off → outside
        res2 = m.score(output={"sum_insured": 1600000}, reference={"sum_insured": 1500000})
        assert res2.value == 0.0

    def test_partial_match_reports_details(self):
        m = NormalizedFieldAccuracy()
        res = m.score(
            output={"sum_insured": 1500000, "annual_premium": 99999},
            reference={"sum_insured": 1500000, "annual_premium": 18000},
        )
        assert res.value == 0.5
        assert "annual_premium" in (res.reason or "")


class TestGates:
    def test_confidence_gate_pass(self):
        m = ConfidenceGate(threshold=0.6)
        res = m.score(output={"label": "HEALTH", "confidence": 0.9})
        assert res.value == 1.0

    def test_confidence_gate_fail(self):
        m = ConfidenceGate(threshold=0.6)
        res = m.score(output={"label": "HEALTH", "confidence": 0.3})
        assert res.value == 0.0

    def test_whitelist_enforcement(self):
        m = WhitelistEnforcement()
        good = m.score(
            output=[{"url": "https://joinditto.in/a"}, {"url": "https://irdai.gov.in/b"}]
        )
        assert good.value == 1.0
        bad = m.score(output=[{"url": "https://evil.example.com/x"}])
        assert bad.value == 0.0

    def test_has_findings(self):
        m = HasFindings()
        assert m.score(output=[]).value == 0.0
        assert m.score(output=[{"url": "x"}]).value == 1.0

    def test_required_fields_present(self):
        m = RequiredFieldsPresent(document_type="HEALTH")
        assert m.score(output={"sum_insured": 1, "annual_premium": 2}).value == 1.0
        assert m.score(output={"sum_insured": 1}).value == 0.0

    def test_short_circuit_correctness(self):
        m = ShortCircuitCorrectness()
        assert m.score(output={"short_circuited": True}, reference=True).value == 1.0
        assert m.score(output={"short_circuited": True}, reference=False).value == 0.0

    def test_xirr_consistency(self):
        m = XirrConsistency()
        res = m.score(output={"analysis": {}}, calc_results={"xirr": 0.038})
        assert res.value == 1.0
        res2 = m.score(output={}, calc_results={})
        assert res2.scoring_failed is True


class TestRobustLLMJudge:
    def test_clean_json(self):
        judge = RobustLLMJudge(
            name="j",
            criteria="be strict",
            llm_client=FakeJudgeLLM(json.dumps({"reasoning": "good", "score": 0.8})),
        )
        res = judge.score(output="X", reference="Y")
        assert res.value == 0.8
        assert res.reason == "good"

    def test_markdown_wrapped_json(self):
        judge = RobustLLMJudge(
            name="j",
            criteria="be strict",
            llm_client=FakeJudgeLLM('```json\n{"reasoning": "ok", "score": 0.5}\n```'),
        )
        res = judge.score(output="X", reference="Y")
        assert res.value == 0.5

    def test_noise_around_json(self):
        judge = RobustLLMJudge(
            name="j",
            criteria="be strict",
            llm_client=FakeJudgeLLM('Here is my eval: {"reasoning": "meh", "score": 0.25} thanks'),
        )
        res = judge.score(output="X", reference="Y")
        assert res.value == 0.25

    def test_no_json_fails_visibly(self):
        judge = RobustLLMJudge(
            name="j", criteria="be strict", llm_client=FakeJudgeLLM("I refuse to evaluate")
        )
        res = judge.score(output="X", reference="Y")
        assert res.scoring_failed is True
        assert res.value == 0.0

    def test_bad_score_out_of_range(self):
        judge = RobustLLMJudge(
            name="j",
            criteria="be strict",
            llm_client=FakeJudgeLLM(json.dumps({"reasoning": "x", "score": 5.0})),
        )
        res = judge.score(output="X", reference="Y")
        assert res.scoring_failed is True


class TestGoldData:
    def test_all_gold_files_parse(self):
        for agent, path in GOLD_FILES.items():
            with open(path, encoding="utf-8") as f:
                gold = json.load(f)
            assert "version" in gold, f"{agent} gold missing version"
            assert "rows" in gold, f"{agent} gold missing rows"
            assert isinstance(gold["rows"], list)

    def test_gold_rows_have_expected_fields(self):
        with open(GOLD_FILES["router"], encoding="utf-8") as f:
            router = json.load(f)
        for row in router["rows"]:
            assert "expected_label" in row
            assert "inputs" in row

        with open(GOLD_FILES["extractor"], encoding="utf-8") as f:
            extractor = json.load(f)
        for row in extractor["rows"]:
            assert "reference" in row
            assert "short_circuited" in row
