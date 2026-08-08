"""Tests for Pydantic extraction schemas."""

import pytest
from pydantic import ValidationError

from policydecoder.schemas import HealthPolicyExtraction, LifePolicyExtraction


class TestHealthPolicyExtraction:
    def test_valid_health_extraction(self):
        data = {
            "policy_name": "Care Supreme",
            "insurer": "Care Health Insurance",
            "plan_type": "individual",
            "sum_insured": 1000000,
            "annual_premium": 15000,
            "room_rent_cap": "₹5,000/day",
            "co_pay_pct": 10,
            "sub_limits": ["ICU cap ₹1,00,000"],
            "waiting_periods": {
                "accident_days": 30,
                "pre_existing_years": 3,
                "specific_disease_years": 2,
            },
            "exclusions": ["maternity", "pre-existing"],
            "restoration": "unlimited",
            "pre_hospitalization_days": 60,
            "post_hospitalization_days": 90,
            "network_hospitals_count": 11400,
            "free_look_days": 15,
            "policy_start_date": "2024-01-01",
        }
        extraction = HealthPolicyExtraction.model_validate(data)
        assert extraction.sum_insured == 1000000
        assert extraction.plan_type == "individual"
        assert extraction.restoration == "unlimited"

    def test_coerces_currency_strings(self):
        """Vision models often emit '₹50,000' or '5,00,000' — must coerce."""
        data = {
            "sum_insured": "₹10,00,000",
            "annual_premium": "₹15,000",
        }
        extraction = HealthPolicyExtraction.model_validate(data)
        assert extraction.sum_insured == 1000000
        assert extraction.annual_premium == 15000

    def test_coerces_indian_number_format(self):
        data = {"sum_insured": "5,00,000", "annual_premium": "12,500"}
        extraction = HealthPolicyExtraction.model_validate(data)
        assert extraction.sum_insured == 500000
        assert extraction.annual_premium == 12500

    def test_required_fields_missing(self):
        extraction = HealthPolicyExtraction.model_validate({})
        missing = extraction.validate_extraction()
        assert "sum_insured" in missing
        assert "annual_premium" in missing

    def test_plan_type_enum(self):
        data = {"plan_type": "family_floater"}
        extraction = HealthPolicyExtraction.model_validate(data)
        assert extraction.plan_type == "family_floater"

    def test_invalid_plan_type_raises(self):
        with pytest.raises(ValidationError):
            HealthPolicyExtraction.model_validate({"plan_type": "not_a_real_type"})


class TestLifePolicyExtraction:
    def test_valid_life_extraction(self):
        data = {
            "policy_name": "LIC Jeevan Anand",
            "policy_type": "endowment",
            "insurer": "LIC",
            "annual_premium": 50000,
            "premium_term_years": 15,
            "policy_term_years": 15,
            "sum_assured": 1000000,
            "policy_start_date": "2022-01-01",
            "maturity_value_at_4pct": 780000,
            "maturity_value_at_8pct": 1120000,
            "charges": {"fund_management_charge_pct": 1.35},
            "free_look_period_days": 15,
            "lock_in_years": 5,
        }
        extraction = LifePolicyExtraction.model_validate(data)
        assert extraction.policy_name == "LIC Jeevan Anand"
        assert extraction.policy_type == "endowment"

    def test_required_fields_missing(self):
        extraction = LifePolicyExtraction.model_validate({})
        missing = extraction.validate_extraction()
        assert "policy_name" in missing
        assert "annual_premium" in missing
        assert "policy_term_years" in missing
        assert "sum_assured" in missing

    def test_round_trips_canned_fixture(self):
        """The existing FakeExtractor canned data should parse cleanly."""
        data = {
            "policy_name": "LIC Jeevan Anand",
            "policy_type": "endowment",
            "insurer": "LIC",
            "annual_premium": 50000,
            "premium_term_years": 15,
            "policy_term_years": 15,
            "sum_assured": 1000000,
            "maturity_value_at_8pct": 1120000,
            "maturity_value_at_4pct": 780000,
            "free_look_period_days": 15,
        }
        extraction = LifePolicyExtraction.model_validate(data)
        assert extraction.validate_extraction() == []
