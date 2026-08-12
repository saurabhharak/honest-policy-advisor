"""Per-product rubric schemas + prompt builders for the page-by-page triage.

Rubrics are structured gold-standard checklists (data/rubrics/*.json): each rule
has the check, threshold, severity, a plain-language explain template, and an
action template — the same data drives BOTH the triage prompt (what to look for)
and the layman-writer prompt (how to explain it).
"""

import json
from pathlib import Path
from typing import Any

from policydecoder.schemas import (
    HealthPolicyExtraction,
    LifePolicyExtraction,
)

# Products the router can return, mapped to their rubric file.
PRODUCTS = ("HEALTH", "LIFE", "TERM")

_RUBRIC_DIR = Path(__file__).resolve().parent.parent / "data" / "rubrics"


def load_rubric_file(product: str) -> dict[str, Any]:
    """Load a rubric from the checked-in data/rubrics/<product>.json."""
    if product not in PRODUCTS:
        raise ValueError(f"Unknown product rubric: {product}")
    with open(_RUBRIC_DIR / f"{product.lower()}.json", encoding="utf-8") as f:
        return json.load(f)


def rubric_rules_text(rubric: dict[str, Any]) -> str:
    """Render the rubric's rules as a checklist block for a prompt."""
    lines = []
    for rule in rubric.get("rules", []):
        threshold = rule.get("threshold")
        t = f" (threshold: {threshold})" if threshold is not None else ""
        lines.append(
            f"- [{rule['id']}] {rule['check']}{t} — severity: {rule.get('severity', 'info')}"
        )
    return "\n".join(lines) if lines else "(no rubric rules)"


def _field_schema_block(product: str) -> str:
    """Render the exact keys the calculators need, so the model returns them."""
    if product == "HEALTH":
        model_fields = HealthPolicyExtraction.model_fields
        extras = (
            '  "waiting_periods": {"accident_days": int, "pre_existing_years": int, '
            '"specific_disease_years": int},\n'
            '  "sub_limits": ["..."],\n'
        )
    else:
        model_fields = LifePolicyExtraction.model_fields  # LIFE and TERM use the life set
        extras = ""
    required = ", ".join(model_fields.keys())
    return (
        "The structured fields you may return (only those visible on this page, "
        f"in exactly these keys):\n{{{{\n  {required},\n{extras}"
        '  "insurer": "string or null"\n}}'
        "\nValues must be numbers (not '₹50,000' strings) for: sum_insured, sum_assured, "
        "annual_premium, maturity_value_at_8pct, maturity_value_at_4pct, co_pay_pct."
    )


def build_triage_prompt(
    product: str,
    rubric: dict[str, Any],
    page_markdown: str,
    page_no: int,
    total_pages: int,
) -> str:
    """Build the per-page triage prompt from the product rubric."""
    return f"""You are reading ONE page of an Indian insurance policy. Two jobs:

(a) Extract the structured fields VISIBLE on this page (partial — omit fields not on this page).
(b) Flag anything a policyholder should be aware of, checked against the checklist below.

CHECKLIST (check every clause on this page against these gold-standard rules):
{rubric_rules_text(rubric)}

{_field_schema_block(product)}

RULES:
- ONLY report fields and findings actually visible on THIS page. Never guess, never infer from other pages.
- If a field isn't on this page, omit it — don't return nulls for everything.
- For each finding, quote the exact source text and give the rubric rule id as category.
- If the page is pure boilerplate (welcome text, images, disclaimers) return empty fields and empty findings.

PAGE {page_no} OF {total_pages}:
{page_markdown}

OUTPUT: strict JSON only, matching:
{{"page_number": {page_no}, "fields": {{...}}, "findings": [{{"category", "severity", "what", "why_concerning", "source_text", "page"}}], "page_summary": "..."}}"""


def build_table_analyzer_prompt(
    product: str,
    rubric: dict[str, Any],
    tables_json: str,
) -> str:
    """Build the global table-analyzer prompt (Track B — whole tables JSON).

    Tables (surrender schedules, premium projections, sub-limit grids) span page
    breaks; Docling/TableFormer stitches them structurally, so this node sees the
    FULL table set and can extract table-centric fields without hallucination.
    """
    return f"""You are analyzing the TABLE data of an Indian insurance policy.

These tables were extracted by a document parser and may span multiple pages
(e.g. Year 1-10 of a surrender schedule on one page, Year 11-20 on the next).
You see the FULL set, so interpret them as one coherent structure.

CHECKLIST (check the tables against these gold-standard rules):
{rubric_rules_text(rubric)}

{_field_schema_block(product)}

RULES:
- Extract table-centric fields ONLY: surrender_value_table, maturity_value_at_4pct,
  maturity_value_at_8pct, premium_term_years, policy_term_years, sum_assured,
  sum_insured, sub_limits, waiting_periods, charges.
- If a value is not in the tables, omit it — never guess.
- For each finding, give the rubric rule id as category and the page range the table spans if known.

== FULL TABLE DATA ==
{tables_json}

OUTPUT: strict JSON only, matching:
{{"fields": {{...}}, "findings": [{{"category", "severity", "what", "why_concerning", "source_text", "page"}}], "table_summary": "..."}}"""


def build_layman_prompt(
    product: str,
    rubric: dict[str, Any],
    merged_fields: dict[str, Any],
    calc_results: dict[str, Any],
    findings: list[dict[str, Any]],
) -> str:
    """Build the layman-writer prompt. Rephrases ONLY — never recomputes."""
    explain_templates = "\n".join(
        f"- {rule['id']}: {rule.get('explain_template', '')} :: {rule.get('action_template', '')}"
        for rule in rubric.get("rules", [])
    )
    return f"""You write plain-language insurance policy explanations for a NON-EXPERT.

All the analysis is already done. You NEVER do arithmetic, NEVER judge whether a
number is good or bad, and NEVER recompute anything. The values below are final.

STRUCTURED POLICY DATA (from extraction):
{json.dumps(merged_fields, ensure_ascii=False, default=str)}

COMPUTED RESULTS (final — from our deterministic calculators, do not touch):
{json.dumps(calc_results, ensure_ascii=False, default=str)}

FINDINGS (already checked against the gold-standard checklist):
{json.dumps(findings, ensure_ascii=False, default=str)}

EXPLANATION + ACTION TEMPLATES (use these to phrase each item):
{explain_templates}

RULES:
- For each finding, write ONE plain-language item: what it is, why it matters to the user, and what to do.
- Use the templates to phrase why_it_matters and what_to_do, filling in actual values from the data.
- Be honest: if there are no concerning findings, say the policy looks fine (verdict GOOD).
- No jargon. A layperson with no insurance knowledge must understand each item.

OUTPUT: strict JSON only, matching:
{{"summary": "...", "items": [{{"severity", "what", "why_it_matters", "what_to_do", "page"}}], "verdict": "GOOD|REVIEW|ALERT"}}"""
