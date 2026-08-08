"""Financial calculations. Pure Python. The LLM never touches this module.

All functions take plain numbers and return plain numbers. No LLM calls,
no channel awareness, no side effects.
"""

from datetime import date

from scipy.optimize import brentq


def xirr(cash_flows: list[tuple[date, float]], guess: float = 0.1) -> float:
    """Calculate XIRR (extended internal rate of return) for irregular cash flows.

    Args:
        cash_flows: list of (date, amount) tuples. Negative = money out (premium).
                    Positive = money in (maturity/surrender value).
        guess: initial guess for the solver.

    Returns:
        Annualized rate of return as a decimal (0.038 = 3.8%).

    Raises:
        ValueError: if cash flows don't have both positive and negative values.
    """
    if not cash_flows:
        raise ValueError("cash_flows cannot be empty")

    amounts = [amt for _, amt in cash_flows]
    if not any(a < 0 for a in amounts) or not any(a > 0 for a in amounts):
        raise ValueError("cash_flows must have both positive and negative values")

    sorted_flows = sorted(cash_flows, key=lambda x: x[0])
    start_date = sorted_flows[0][0]

    def npv(rate: float) -> float:
        total = 0.0
        for d, amount in sorted_flows:
            years = (d - start_date).days / 365.25
            total += amount / (1 + rate) ** years
        return total

    try:
        return brentq(npv, -0.99, 10.0, xtol=1e-6)
    except ValueError as e:
        raise ValueError("XIRR did not converge — check cash flow data") from e


def policy_cash_flows(
    annual_premium: float,
    premium_term_years: int,
    policy_term_years: int,
    maturity_value: float,
    start_date: date | None = None,
) -> list[tuple[date, float]]:
    """Build the cash flow list for a life insurance policy.

    Premiums are negative (money out). Maturity value is positive (money in).
    Premiums are paid at the start of each year.
    """
    if start_date is None:
        start_date = date.today()

    flows = []
    for year in range(premium_term_years):
        premium_date = date(start_date.year + year, start_date.month, start_date.day)
        flows.append((premium_date, -annual_premium))

    maturity_date = date(start_date.year + policy_term_years, start_date.month, start_date.day)
    flows.append((maturity_date, maturity_value))

    return flows


def term_plus_sip_value(
    annual_premium: float,
    term_annual_cost: float,
    investment_years: int,
    expected_return: float = 0.11,
) -> float:
    """Calculate the future value of buying term insurance and investing the rest.

    Args:
        annual_premium: what the user currently pays per year.
        term_annual_cost: what a term plan would cost per year.
        investment_years: how many years the difference is invested.
        expected_return: annual return assumption for the SIP (default 11%).

    Returns:
        Future value of the SIP at the end of the investment period.
    """
    annual_sip = annual_premium - term_annual_cost
    if annual_sip <= 0:
        return 0.0

    # Future value of an annuity due (payments at start of period)
    fv = (
        annual_sip
        * (((1 + expected_return) ** investment_years - 1) / expected_return)
        * (1 + expected_return)
    )
    return round(fv, 2)


def surrender_loss(
    premiums_paid: float,
    surrender_value: float,
) -> float:
    """How much the user loses if they surrender today.

    Returns the absolute loss amount (positive number = money lost).
    """
    return max(0.0, premiums_paid - surrender_value)


def opportunity_cost(
    policy_maturity: float,
    term_sip_maturity: float,
) -> float:
    """How much more the user would have had with term+SIP.

    Returns the difference. Positive = user lost money by choosing the policy.
    """
    return term_sip_maturity - policy_maturity


def estimate_term_cost(age: int, sum_assured: float = 10_000_000) -> float:
    """Rough estimate of annual term insurance premium.

    Based on typical rates for a healthy non-smoker in India.
    ₹1 crore cover, 30-year term.
    """
    # Approximate annual premium per ₹1 lakh of sum assured
    if age <= 25:
        rate = 60
    elif age <= 30:
        rate = 80
    elif age <= 35:
        rate = 100
    elif age <= 40:
        rate = 130
    elif age <= 45:
        rate = 180
    elif age <= 50:
        rate = 260
    else:
        rate = 380

    return (sum_assured / 100_000) * rate


def format_inr(amount: float) -> str:
    """Format a number as Indian rupees with lakh/crore notation."""
    if amount >= 1_00_00_000:
        return f"₹{amount / 1_00_00_000:.1f} crore"
    if amount >= 1_00_000:
        return f"₹{amount / 1_00_000:.1f} lakh"
    if amount >= 1_000:
        return f"₹{amount:,.0f}"
    return f"₹{amount:.2f}"
