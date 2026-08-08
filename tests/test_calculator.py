"""Tests for the financial calculator. Pure Python, no LLM."""

from datetime import date

import pytest

from policydecoder.calculator import (
    estimate_term_cost,
    format_inr,
    opportunity_cost,
    policy_cash_flows,
    surrender_loss,
    term_plus_sip_value,
    xirr,
)


class TestXIRR:
    def test_simple_policy(self):
        """A policy paying ₹50K/year for 15 years, maturing at ₹11.2L."""
        flows = policy_cash_flows(
            annual_premium=50000,
            premium_term_years=15,
            policy_term_years=15,
            maturity_value=1120000,
            start_date=date(2024, 1, 1),
        )
        result = xirr(flows)
        assert 0.02 < result < 0.05  # should be around 3-4%

    def test_high_return_policy(self):
        """A policy that returns 8% should show ~8% XIRR."""
        flows = policy_cash_flows(
            annual_premium=100000,
            premium_term_years=10,
            policy_term_years=10,
            maturity_value=1560000,
            start_date=date(2024, 1, 1),
        )
        result = xirr(flows)
        assert 0.06 < result < 0.10

    def test_empty_flows_raises(self):
        with pytest.raises(ValueError, match="empty"):
            xirr([])

    def test_all_negative_raises(self):
        flows = [(date(2024, 1, 1), -50000), (date(2025, 1, 1), -50000)]
        with pytest.raises(ValueError, match="positive and negative"):
            xirr(flows)


class TestPolicyCashFlows:
    def test_correct_number_of_flows(self):
        flows = policy_cash_flows(50000, 15, 15, 1120000, date(2024, 1, 1))
        assert len(flows) == 16  # 15 premiums + 1 maturity

    def test_premiums_are_negative(self):
        flows = policy_cash_flows(50000, 5, 10, 500000, date(2024, 1, 1))
        premiums = [amt for _, amt in flows if amt < 0]
        assert len(premiums) == 5
        assert all(p == -50000 for p in premiums)

    def test_maturity_is_positive(self):
        flows = policy_cash_flows(50000, 5, 10, 500000, date(2024, 1, 1))
        maturity = [amt for _, amt in flows if amt > 0]
        assert len(maturity) == 1
        assert maturity[0] == 500000


class TestTermPlusSIP:
    def test_positive_difference(self):
        """Term+SIP should be worth more than the policy."""
        result = term_plus_sip_value(
            annual_premium=50000,
            term_annual_cost=5000,
            investment_years=15,
            expected_return=0.11,
        )
        assert result > 0

    def test_zero_if_term_costs_more(self):
        result = term_plus_sip_value(
            annual_premium=5000,
            term_annual_cost=6000,
            investment_years=15,
        )
        assert result == 0.0

    def test_known_value(self):
        """₹45K/year for 15 years at 11% should give roughly ₹17.5L."""
        result = term_plus_sip_value(50000, 5000, 15, 0.11)
        assert 1_500_000 < result < 2_000_000


class TestSurrenderLoss:
    def test_loss_when_surrender_less(self):
        assert surrender_loss(100000, 30000) == 70000

    def test_no_loss_when_surrender_more(self):
        assert surrender_loss(100000, 100000) == 0.0


class TestOpportunityCost:
    def test_positive_when_sip_better(self):
        assert opportunity_cost(1120000, 1980000) == 860000

    def test_negative_when_policy_better(self):
        assert opportunity_cost(2000000, 1500000) == -500000


class TestEstimateTermCost:
    def test_younger_is_cheaper(self):
        cost_25 = estimate_term_cost(25)
        cost_45 = estimate_term_cost(45)
        assert cost_25 < cost_45

    def test_reasonable_range(self):
        cost = estimate_term_cost(30, 10_000_000)
        assert 3000 < cost < 15000


class TestFormatINR:
    def test_lakhs(self):
        assert format_inr(500000) == "₹5.0 lakh"

    def test_crores(self):
        assert format_inr(15000000) == "₹1.5 crore"

    def test_thousands(self):
        assert format_inr(5000) == "₹5,000"
