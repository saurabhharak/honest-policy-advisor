"""The triage LLM's `fields` is untyped JSON — a wrong type must be sanitized
before it reaches the deterministic calculators (never crashes score_health_policy).
"""

from policydecoder.graph.triage import _sanitize_extraction


def test_sanitize_drops_boolean_restoration():
    """restoration: true (bool) must be dropped, not crash the calculator."""
    extraction = {
        "sum_insured": 1500000,
        "annual_premium": 34526,
        "restoration": True,  # wrong type — the LLM returned a bool
        "room_rent_cap": "no cap",
        "co_pay_pct": 10,
    }
    cleaned = _sanitize_extraction(extraction, "HEALTH")
    assert "restoration" not in cleaned or cleaned["restoration"] is None
    assert cleaned["sum_insured"] == 1500000  # good fields survive


def test_sanitize_coerces_string_numbers():
    """String numbers ('₹34,526') are coerced to floats by the schema."""
    extraction = {"annual_premium": "₹34,526", "sum_insured": "15,00,000"}
    cleaned = _sanitize_extraction(extraction, "HEALTH")
    assert cleaned["annual_premium"] == 34526.0
    assert cleaned["sum_insured"] == 1500000.0


def test_sanitize_keeps_extra_keys():
    """insurer (needed for the ICR benchmark lookup) passes through."""
    extraction = {"sum_insured": 1000000, "annual_premium": 20000, "insurer": "HDFC Ergo"}
    cleaned = _sanitize_extraction(extraction, "HEALTH")
    assert cleaned["insurer"] == "HDFC Ergo"
