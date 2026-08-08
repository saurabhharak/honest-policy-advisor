"""Health insurance scoring. Pure Python. The LLM never touches this module.

Takes the extracted health policy fields + an insurer benchmark row and
produces deterministic flags and an overall verdict. Every function is a
pure function of its inputs — no LLM, no channel awareness, no side effects.

Thresholds follow the guidance in Ditto's "How to Choose Health Insurance"
and IRDAI's published data conventions.
"""

import re
from typing import Any

# ICR bands (IRDAI FY2024-25 data, per industry guidance)
ICR_HEALTHY_LOW = 70.0
ICR_HEALTHY_HIGH = 90.0
ICR_STRESS = 95.0

SOLVENCY_MINIMUM = 1.5

CO_PAY_FLAG_ABOVE = 20.0
ACCIDENT_WAIT_OK_DAYS = 30
PED_WAIT_OK_YEARS = 4
SPECIFIC_DISEASE_OK_YEARS = 3
NETWORK_MIN_HOSPITALS = 5000
ROOM_RENT_CAP_OK_DAY = 3000  # a per-day cap at or above this is reasonable


class HealthScoreReport(dict):
    """A dict subclass so callers get dict ergonomics with type hints."""


def room_rent_cap_assessment(
    sum_insured: float | None, room_rent_cap: str | None
) -> str | None:
    """Flag restrictive room rent caps.

    A per-day cap below ~₹3,000 essentially confines you to a shared ward,
    and the room component then eats a large share of the sum insured on a
    multi-day stay. %-of-SI caps and 'no cap' are fine.
    """
    if not room_rent_cap:
        return None
    cap = room_rent_cap.strip().lower()
    if cap in ("no cap", "no limit", "unlimited", "none"):
        return None
    # Percentage-of-SI caps are a reasonable design
    if re.search(r"\d+\s*%", cap):
        return None
    # Extract a per-day rupee amount
    match = re.search(r"[\d,]+", cap.replace("₹", ""))
    if not match:
        return None
    amount = float(match.group().replace(",", ""))
    if amount < ROOM_RENT_CAP_OK_DAY:
        return (
            f"Room rent cap of {room_rent_cap} is restrictive — below "
            f"₹{ROOM_RENT_CAP_OK_DAY:,}/day it confines you to a shared ward, "
            "and the room cost eats a large share of your sum insured on a "
            "multi-day stay."
        )
    return None


def co_pay_assessment(co_pay_pct: float | None) -> str | None:
    """Flag co-pay above 20% — the policyholder bears too much."""
    if co_pay_pct is None:
        return None
    if co_pay_pct > CO_PAY_FLAG_ABOVE:
        return (
            f"Co-pay of {co_pay_pct:.0f}% is high — you pay that share of "
            "every claim out of pocket."
        )
    return None


def waiting_period_assessment(waiting_periods: dict | None) -> str | None:
    """Flag waiting periods worse than the standard benchmarks."""
    if not waiting_periods:
        return None
    issues = []
    accident_days = waiting_periods.get("accident_days")
    if accident_days and accident_days > ACCIDENT_WAIT_OK_DAYS:
        issues.append(
            f"accident waiting period of {accident_days} days "
            f"(standard is {ACCIDENT_WAIT_OK_DAYS} days)"
        )
    pre_existing = waiting_periods.get("pre_existing_years")
    if pre_existing and pre_existing > PED_WAIT_OK_YEARS:
        issues.append(
            f"pre-existing disease waiting of {pre_existing} years "
            f"(standard is up to {PED_WAIT_OK_YEARS} years)"
        )
    specific = waiting_periods.get("specific_disease_years")
    if specific and specific > SPECIFIC_DISEASE_OK_YEARS:
        issues.append(
            f"specific disease waiting of {specific} years "
            f"(standard is up to {SPECIFIC_DISEASE_OK_YEARS} years)"
        )
    return "; ".join(issues) if issues else None


_HIDDEN_SUBLIMIT_KEYWORDS = (
    "icu",
    "c-section",
    "c section",
    "cesarean",
    "cataract",
    "dialysis",
)


def sub_limit_assessment(sub_limits: list[str] | None) -> str | None:
    """Flag sub-limits on common high-cost procedures."""
    if not sub_limits:
        return None
    hits = [
        s for s in sub_limits if any(k in s.lower() for k in _HIDDEN_SUBLIMIT_KEYWORDS)
    ]
    if hits:
        return (
            "Sub-limits on common procedures: " + ", ".join(hits) +
            ". These cap payouts on the treatments most families actually claim."
        )
    return None


def restoration_assessment(restoration: str | None) -> str | None:
    """Warn if restoration is missing or limited."""
    if restoration is None:
        return None
    if restoration.lower() in ("none", "limited"):
        return (
            f"Restoration benefit is '{restoration}' — if the sum insured is "
            "exhausted, you get no (or limited) automatic top-up for the rest "
            "of the year."
        )
    return None


def network_assessment(network_hospitals_count: int | None) -> str | None:
    """Warn if the cashless network is too small."""
    if network_hospitals_count is None:
        return None
    if network_hospitals_count < NETWORK_MIN_HOSPITALS:
        return (
            f"Only {network_hospitals_count:,} network hospitals — cashless "
            f"treatment may be hard to find near you "
            f"(benchmark: {NETWORK_MIN_HOSPITALS:,}+)."
        )
    return None


def fit_score(
    sum_insured: float | None,
    city_tier: str = "metro",
    age: int | None = None,
) -> str | None:
    """Adequacy check: does the cover match the person's city and age?"""
    if not sum_insured:
        return None
    if city_tier == "metro" and sum_insured < 15_00_000:
        return (
            f"Sum insured of ₹{sum_insured / 100000:.1f}L is below the "
            "₹15-25L recommendation for metro cities."
        )
    if city_tier != "metro" and sum_insured < 10_00_000:
        return (
            f"Sum insured of ₹{sum_insured / 100000:.1f}L is below the "
            "₹10L recommendation for smaller cities."
        )
    return None


def insurer_benchmark_score(insurer_metrics: dict | None) -> dict[str, Any]:
    """Score the insurer against IRDAI-published benchmarks.

    Returns a dict with statuses. Never fabricates a number for missing
    data — missing metrics are 'no_data'.
    """
    if not insurer_metrics:
        return {
            "insurer": "unknown",
            "icr_status": "no_data",
            "icr_value": None,
            "solvency_status": "no_data",
            "complaints_status": "no_data",
            "network_status": "no_data",
        }

    icr = insurer_metrics.get("icr_fy25")
    if icr is None:
        icr_status = "no_data"
    elif icr < ICR_HEALTHY_LOW:
        icr_status = "restrictive"
    elif icr > ICR_STRESS:
        icr_status = "stress"
    else:
        icr_status = "healthy"

    solvency = insurer_metrics.get("solvency_ratio")
    if solvency is None:
        solvency_status = "no_data"
    elif solvency < SOLVENCY_MINIMUM:
        solvency_status = "below_minimum"
    else:
        solvency_status = "healthy"

    complaints = insurer_metrics.get("complaints_per_10k_claims")
    if complaints is None:
        complaints_status = "no_data"
    elif complaints <= 10:
        complaints_status = "low"
    else:
        complaints_status = "high"

    network = insurer_metrics.get("network_hospitals")
    if network is None:
        network_status = "no_data"
    elif network >= NETWORK_MIN_HOSPITALS:
        network_status = "healthy"
    else:
        network_status = "small"

    return {
        "insurer": insurer_metrics.get("name", "unknown"),
        "icr_status": icr_status,
        "icr_value": icr,
        "solvency_status": solvency_status,
        "complaints_status": complaints_status,
        "network_status": network_status,
    }


def score_health_policy(
    extraction: dict[str, Any],
    insurer_metrics: dict | None,
    user_context: dict[str, Any] | None = None,
) -> HealthScoreReport:
    """Aggregate all assessments into a health policy score report.

    Returns a dict:
    {
        "overall": "GOOD" | "REVIEW" | "ALERT",
        "policy_flags": [...],
        "insurer_metrics": {...},
        "extracted": {...}
    }
    """
    user_context = user_context or {}
    city_tier = user_context.get("city_tier", "metro")
    age = user_context.get("age")

    flags: list[str] = []
    for check in (
        room_rent_cap_assessment(
            extraction.get("sum_insured"), extraction.get("room_rent_cap")
        ),
        co_pay_assessment(extraction.get("co_pay_pct")),
        waiting_period_assessment(extraction.get("waiting_periods")),
        sub_limit_assessment(extraction.get("sub_limits")),
        restoration_assessment(extraction.get("restoration")),
        network_assessment(extraction.get("network_hospitals_count")),
        fit_score(extraction.get("sum_insured"), city_tier, age),
    ):
        if check:
            flags.append(check)

    benchmark = insurer_benchmark_score(insurer_metrics)

    # Overall verdict: any policy red flag → REVIEW; any insurer stress or
    # multiple flags → ALERT; a genuinely clean policy → GOOD.
    severity = 0
    if benchmark["icr_status"] == "stress":
        severity += 2
    if benchmark["solvency_status"] == "below_minimum":
        severity += 1
    severity += len(flags)

    if severity >= 3:
        overall = "ALERT"
    elif severity >= 1:
        overall = "REVIEW"
    else:
        overall = "GOOD"

    return HealthScoreReport(
        overall=overall,
        policy_flags=flags,
        insurer_metrics=benchmark,
        extracted=extraction,
    )
