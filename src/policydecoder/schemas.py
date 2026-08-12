"""Pydantic extraction schemas for policy documents.

Separate schemas per document type so the vision model is never asked to
extract health fields from a life policy (or vice versa). The router
(classifier) decides which schema to use.

Numbers are coerced from strings because vision models frequently emit
values like "₹50,000" or "5,00,000" instead of clean integers.
"""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator


def _to_float(v: Any) -> float | None:
    """Coerce '₹50,000', '5,00,000', '10 lakh' etc. to a number."""
    if v is None or v == "":
        return None
    if isinstance(v, int | float):
        return float(v)
    s = str(v).strip().replace(",", "").replace("₹", "").replace(" ", "")
    # Handle lakh/crore words
    lower = s.lower()
    multiplier = 1.0
    for word, mult in (("crore", 1e7), ("lakh", 1e5)):
        if word in lower:
            multiplier = mult
            lower = lower.replace(word, "")
            break
    try:
        return float(lower) * multiplier
    except ValueError:
        return None


class PlanType(StrEnum):
    INDIVIDUAL = "individual"
    FAMILY_FLOATER = "family_floater"
    SENIOR = "senior"
    TOPUP = "topup"
    SUPER_TOPUP = "super_topup"
    OTHER = "other"


class RestorationType(StrEnum):
    UNLIMITED = "unlimited"
    LIMITED = "limited"
    NONE = "none"


class WaitingPeriods(BaseModel):
    accident_days: int | None = None
    pre_existing_years: int | None = None
    specific_disease_years: int | None = None


class HealthPolicyExtraction(BaseModel):
    """Structured fields extracted from a health insurance policy document."""

    model_config = ConfigDict(use_enum_values=True)

    policy_name: str | None = None
    insurer: str | None = None
    plan_type: PlanType | None = None
    sum_insured: float | None = None
    annual_premium: float | None = None
    room_rent_cap: str | None = None  # "no cap", "₹5,000/day", "1% of SI"
    co_pay_pct: float | None = None
    sub_limits: list[str] = []
    waiting_periods: WaitingPeriods | None = None
    exclusions: list[str] = []
    restoration: RestorationType | None = None
    pre_hospitalization_days: int | None = None
    post_hospitalization_days: int | None = None
    network_hospitals_count: int | None = None
    free_look_days: int | None = None
    policy_start_date: str | None = None

    @field_validator("sum_insured", "annual_premium", "co_pay_pct", mode="before")
    @classmethod
    def _coerce_numbers(cls, v: Any) -> Any:
        if isinstance(v, str):
            return _to_float(v)
        return v

    @field_validator(
        "pre_hospitalization_days",
        "post_hospitalization_days",
        "network_hospitals_count",
        "free_look_days",
        mode="before",
    )
    @classmethod
    def _coerce_ints(cls, v: Any) -> Any:
        if isinstance(v, str):
            num = _to_float(v)
            return int(num) if num is not None else None
        return v

    def validate_extraction(self) -> list[str]:
        """Return list of missing required fields. Empty = usable."""
        required = ["sum_insured", "annual_premium"]
        return [f for f in required if not getattr(self, f)]


class LifePolicyExtraction(BaseModel):
    """Structured fields extracted from a life insurance policy document."""

    model_config = ConfigDict(use_enum_values=True)

    policy_name: str | None = None
    policy_type: (
        Literal["ulip", "endowment", "money_back", "whole_life", "term", "pension", "other"] | None
    ) = None
    insurer: str | None = None
    annual_premium: float | None = None
    premium_term_years: int | None = None
    policy_term_years: int | None = None
    sum_assured: float | None = None
    policy_start_date: str | None = None
    maturity_value_at_4pct: float | None = None
    maturity_value_at_8pct: float | None = None
    charges: dict[str, Any] = {}
    surrender_value_table: str | None = None
    free_look_period_days: int | None = None
    lock_in_years: int | None = None

    @field_validator(
        "annual_premium",
        "sum_assured",
        "maturity_value_at_4pct",
        "maturity_value_at_8pct",
        mode="before",
    )
    @classmethod
    def _coerce_numbers(cls, v: Any) -> Any:
        if isinstance(v, str):
            return _to_float(v)
        return v

    @field_validator(
        "premium_term_years",
        "policy_term_years",
        "free_look_period_days",
        "lock_in_years",
        mode="before",
    )
    @classmethod
    def _coerce_ints(cls, v: Any) -> Any:
        if isinstance(v, str):
            num = _to_float(v)
            return int(num) if num is not None else None
        return v

    def validate_extraction(self) -> list[str]:
        """Return list of missing required fields. Empty = usable."""
        required = ["policy_name", "annual_premium", "policy_term_years", "sum_assured"]
        return [f for f in required if not getattr(self, f)]


class PageFinding(BaseModel):
    """One concern flagged on a single page by the page-triage LLM."""

    category: str  # rubric rule id, e.g. "co_pay"
    severity: Literal["info", "warning", "alert"]
    what: str  # the fact as it appears on the page
    why_concerning: str  # plain-language why it matters
    source_text: str  # short verbatim quote from the page
    page: int | None = None  # None for table findings spanning a page range


class PageTriageOutput(BaseModel):
    """Strict JSON contract for one page of the page-by-page triage."""

    page_number: int
    fields: dict[str, Any] = {}  # PARTIAL extraction — only text fields visible on THIS page
    findings: list[PageFinding] = []
    page_summary: str = ""  # one line: what this page is


class TableAnalysisOutput(BaseModel):
    """Strict JSON contract for the global table-analyzer node (whole tables JSON).

    Table-centric fields that need whole-table context (surrender schedules,
    premium projections, sub-limit grids) — Docling/TableFormer stitches these
    across page breaks structurally, so this node sees the FULL tables.
    """

    fields: dict[str, Any] = {}
    findings: list[PageFinding] = []
    table_summary: str = ""


class LaymanItem(BaseModel):
    """One plain-language explanation item for the user-facing verdict."""

    severity: Literal["info", "warning", "alert"]
    what: str  # "Co-pay of 30% on claims"
    why_it_matters: str  # from rubric explain_template + actual values
    what_to_do: str  # from rubric action_template
    page: int | None = None


class LaymanVerdict(BaseModel):
    """Final plain-language verdict produced by the layman-writer LLM."""

    summary: str
    items: list[LaymanItem] = []
    verdict: Literal["GOOD", "REVIEW", "ALERT"]
