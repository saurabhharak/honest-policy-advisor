"""Tests for the health insurance scoring calculator. Pure Python, no LLM."""

from policydecoder.health_calculator import (
    co_pay_assessment,
    insurer_benchmark_score,
    network_assessment,
    restoration_assessment,
    room_rent_cap_assessment,
    score_health_policy,
    sub_limit_assessment,
    waiting_period_assessment,
)

GOOD_INSURER = {
    "name": "HDFC Ergo General Insurance",
    "icr_fy25": 84.85,
    "solvency_ratio": 2.4,
    "complaints_per_10k_claims": 5.0,
    "network_hospitals": 13000,
    "source_url": "https://irdai.gov.in/annual-report",
    "as_of": "2025-12-30",
}

STRESSED_INSURER = {
    "name": "National Insurance",
    "icr_fy25": 96.05,
    "solvency_ratio": None,
    "complaints_per_10k_claims": None,
    "network_hospitals": None,
    "source_url": "https://irdai.gov.in/annual-report",
    "as_of": "2025-12-30",
}

UNKNOWN_INSURER = {"name": "Unknown Co", "icr_fy25": None}


class TestRoomRentCap:
    def test_2000_per_day_cap_flags(self):
        """₹2k/day confines you to a shared ward — a value leak."""
        result = room_rent_cap_assessment(1_000_000, "₹2,000/day")
        assert result is not None
        assert "flagged" in result.lower() or "cap" in result.lower()

    def test_no_cap_no_flag(self):
        assert room_rent_cap_assessment(1_000_000, "no cap") is None

    def test_none_cap_no_flag(self):
        assert room_rent_cap_assessment(1_000_000, None) is None

    def test_percentage_cap_no_flag(self):
        """A %-of-SI cap like 2% is a reasonable design, not a leak."""
        assert room_rent_cap_assessment(1_000_000, "2% of SI") is None


class TestCoPay:
    def test_high_copay_flags(self):
        assert co_pay_assessment(25) is not None

    def test_low_copay_ok(self):
        assert co_pay_assessment(10) is None

    def test_none_ok(self):
        assert co_pay_assessment(None) is None


class TestWaitingPeriods:
    def test_long_accident_waiting_flags(self):
        result = waiting_period_assessment(
            {"accident_days": 90, "pre_existing_years": 2, "specific_disease_years": 2}
        )
        assert result is not None

    def test_standard_waiting_ok(self):
        result = waiting_period_assessment(
            {"accident_days": 30, "pre_existing_years": 3, "specific_disease_years": 2}
        )
        assert result is None

    def test_none_ok(self):
        assert waiting_period_assessment(None) is None


class TestSubLimits:
    def test_common_hidden_caps_flag(self):
        result = sub_limit_assessment(["ICU cap ₹1,00,000", "c-section limit"])
        assert result is not None
        assert "ICU" in result or "icu" in result

    def test_no_sublimits_ok(self):
        assert sub_limit_assessment([]) is None


class TestRestoration:
    def test_no_restoration_warns(self):
        assert restoration_assessment("none") is not None

    def test_unlimited_ok(self):
        assert restoration_assessment("unlimited") is None

    def test_limited_warns(self):
        assert restoration_assessment("limited") is not None


class TestNetwork:
    def test_small_network_warns(self):
        assert network_assessment(3000) is not None

    def test_large_network_ok(self):
        assert network_assessment(12000) is None

    def test_none_ok(self):
        assert network_assessment(None) is None


class TestInsurerBenchmark:
    def test_healthy_icr_ok(self):
        result = insurer_benchmark_score(GOOD_INSURER)
        assert result["icr_status"] == "healthy"

    def test_stressed_icr_flags(self):
        """ICR >95% means the insurer may be financially stressed."""
        result = insurer_benchmark_score(STRESSED_INSURER)
        assert result["icr_status"] == "stress"

    def test_unknown_icr_no_number(self):
        """No data → 'no data', never a fabricated number."""
        result = insurer_benchmark_score(UNKNOWN_INSURER)
        assert result["icr_status"] == "no_data"

    def test_low_solvency_flags(self):
        data = dict(GOOD_INSURER, solvency_ratio=1.2)
        result = insurer_benchmark_score(data)
        assert result["solvency_status"] == "below_minimum"


class TestScoreHealthPolicy:
    def test_known_good_policy_returns_good(self):
        extraction = {
            "policy_name": "Care Supreme",
            "insurer": "HDFC Ergo General Insurance",
            "plan_type": "individual",
            "sum_insured": 15_00_000,
            "annual_premium": 15000,
            "room_rent_cap": "no cap",
            "co_pay_pct": 10,
            "waiting_periods": {
                "accident_days": 30,
                "pre_existing_years": 3,
                "specific_disease_years": 2,
            },
            "sub_limits": [],
            "restoration": "unlimited",
            "network_hospitals_count": 13000,
            "pre_hospitalization_days": 60,
            "post_hospitalization_days": 90,
        }
        report = score_health_policy(extraction, GOOD_INSURER, {})
        assert report["overall"] == "GOOD"

    def test_known_bad_policy_returns_alert(self):
        extraction = {
            "policy_name": "Bad Plan",
            "insurer": "National Insurance",
            "plan_type": "individual",
            "sum_insured": 5_00_000,
            "annual_premium": 25000,
            "room_rent_cap": "₹2,000/day",
            "co_pay_pct": 30,
            "waiting_periods": {
                "accident_days": 90,
                "pre_existing_years": 5,
                "specific_disease_years": 4,
            },
            "sub_limits": ["ICU cap ₹50,000"],
            "restoration": "none",
            "network_hospitals_count": 2000,
        }
        report = score_health_policy(extraction, STRESSED_INSURER, {})
        assert report["overall"] == "ALERT"

    def test_mixed_policy_returns_review(self):
        extraction = {
            "policy_name": "Mid Plan",
            "insurer": "Unknown Co",
            "sum_insured": 10_00_000,
            "annual_premium": 18000,
            "room_rent_cap": "no cap",
            "co_pay_pct": 10,
            "restoration": "limited",
            "network_hospitals_count": 6000,
        }
        report = score_health_policy(extraction, UNKNOWN_INSURER, {})
        assert report["overall"] == "REVIEW"
