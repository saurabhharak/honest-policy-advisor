"""The exact field contract: keys the triage/table model must produce so the
deterministic calculators work. The LLM supplies VALUES; Python does the math.
"""

from policydecoder.calculator import life_calc
from policydecoder.graph.rubrics import (
    HealthPolicyExtraction,
    LifePolicyExtraction,
)
from policydecoder.health_calculator import score_health_policy


def test_life_calc_contract_keys():
    """These are the exact keys the triage/table model must return for LIFE."""
    data = {
        "policy_name": "Jeevan Anand",
        "policy_type": "endowment",
        "insurer": "LIC",
        "annual_premium": 50000,
        "premium_term_years": 15,
        "policy_term_years": 15,
        "sum_assured": 1000000,
        "maturity_value_at_8pct": 1120000,
        "maturity_value_at_4pct": 780000,
        "policy_start_date": "2022-01-01",
        "free_look_period_days": 15,
    }
    calc = life_calc(data, user_age=30)
    assert calc["xirr"] > 0  # real XIRR from the contract keys
    assert calc["premiums_paid"] > 0
    assert calc["free_look_days"] == 15


def test_life_calc_contract_validation():
    """A model returning wrong types for a key is coerced to None (safe), not
    silently passed to life_calc as garbage."""
    bad = {"annual_premium": "fifty thousand", "policy_term_years": "many"}
    parsed = LifePolicyExtraction.model_validate({**bad, "policy_name": "X"})
    # Coercion failure → None, so life_calc treats it as absent, never as a bad number.
    assert parsed.annual_premium is None
    assert parsed.policy_term_years is None
    # And life_calc with missing values returns safe zeros (no crash).
    calc = life_calc({"policy_name": "X"}, user_age=30)
    assert calc["xirr"] == 0.0


def test_health_calc_contract_keys():
    """These are the exact keys the triage/table model must return for HEALTH."""
    data = {
        "sum_insured": 1500000,
        "annual_premium": 34526,
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
        "pre_hospitalization_days": 30,
        "post_hospitalization_days": 90,
        "free_look_days": 30,
    }
    report = score_health_policy(data, None, {})
    assert report["overall"] in ("GOOD", "REVIEW", "ALERT")
    # No co-pay flag, no room-rent flag, healthy network → no flags
    assert "co-pay" not in " ".join(report["policy_flags"]).lower()


def test_health_schema_has_new_ditto_fields():
    """pre/post-hospitalization days (Ditto must-haves) are in the health schema."""
    fields = HealthPolicyExtraction.model_fields
    assert "pre_hospitalization_days" in fields
    assert "post_hospitalization_days" in fields
