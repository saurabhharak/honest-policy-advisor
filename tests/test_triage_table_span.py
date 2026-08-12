"""Cross-page table-span guard: a table split across pages must be recovered by
the global table track, never hallucinated by page-local triage, and life_calc
must compute the right XIRR from the merged result.
"""

from policydecoder.calculator import life_calc
from policydecoder.graph.triage import accumulate


def test_accumulate_recovers_cross_page_table_via_table_track():
    """Page 14 has columns headers + Year 1-10; page 15 has Year 11-20.

    Track A (page triage) sees column-less rows on page 15 → returns no table
    fields. Track B (table analyzer) sees the WHOLE stitched table → returns
    the full schedule + the maturity value. accumulate must prefer Track B's
    table fields.
    """
    # Page triage (Track A) correctly reports it CANNOT interpret the columns on
    # the continuation page — it omits the table fields rather than hallucinate.
    page_14 = {
        "page_number": 14,
        "fields": {"policy_name": "ULIP X"},
        "findings": [],
        "page_summary": "surrender schedule part 1",
    }
    page_15 = {
        "page_number": 15,
        "fields": {},
        "findings": [],
        "page_summary": "surrender schedule part 2 (column continuation)",
    }

    # Table analyzer (Track B) sees the WHOLE stitched table and extracts the
    # values the calculators need — the maturity value at 8%.
    table_out = {
        "fields": {
            "policy_name": "ULIP X",
            "annual_premium": 50000,
            "premium_term_years": 15,
            "policy_term_years": 15,
            "sum_assured": 1000000,
            "maturity_value_at_8pct": 1120000,
            "maturity_value_at_4pct": 780000,
            "surrender_value_table": "Year 1-20 surrender schedule (stitched)",
        },
        "findings": [],
        "table_summary": "full surrender schedule spanning pages 14-15",
    }

    state = {
        "page_outputs": [page_14, page_15],
        "table_output": table_out,
        "findings": [],
    }
    merged = accumulate(state, None)["extraction"]

    # The maturity value (from the stitched table) reached the merged fields.
    assert merged["maturity_value_at_8pct"] == 1120000
    assert merged["surrender_value_table"].startswith("Year 1-20")

    # life_calc computes a real XIRR from the merged data — not zero, not garbage.
    calc = life_calc(merged, user_age=30)
    assert calc["xirr"] > 0
    assert calc["term_sip_value"] > calc["policy_maturity"]  # SIP beats policy


def test_page_triage_alone_would_hallucinate_without_table_track():
    """The fatal-flaw scenario: page-15-only triage has no column headers.

    If we relied on page triage alone, the continuation-page rows would be
    interpreted with wrong columns → wrong maturity value. The accumulate
    node must NOT take page-track fields for table-centric keys when the
    table track provided them.
    """
    # A hallucinating page triage might guess a wrong maturity value from the
    # column-less page 15. accumulate must prefer the table track's value.
    page_15_hallucinated = {
        "page_number": 15,
        "fields": {"maturity_value_at_8pct": 999999999},  # hallucinated from column-less rows
        "findings": [],
        "page_summary": "wrong guess",
    }
    table_out = {
        "fields": {"maturity_value_at_8pct": 1120000},
        "findings": [],
        "table_summary": "",
    }
    merged = accumulate(
        {"page_outputs": [page_15_hallucinated], "table_output": table_out, "findings": []}, None
    )["extraction"]
    # Table track wins for table-centric fields because it saw the real structure.
    assert merged["maturity_value_at_8pct"] == 1120000


def test_annual_premium_table_track_wins_for_family_floater():
    """A health family-floater premium table lists one row per insured person.

    Page-local triage only saw the FIRST person's row (₹25,826) — the whole-
    table track saw BOTH rows and summed them (₹34,526). The table track must
    be authoritative for annual_premium, like the other cross-page table fields.
    """
    page_premium_partial = {
        "page_number": 2,
        "fields": {"annual_premium": 25825.98},  # father only — page-local miss
        "findings": [],
        "page_summary": "premium table page",
    }
    table_out = {
        "fields": {
            "sum_insured": 1500000,
            "annual_premium": 34526.14,  # 25825.98 + 8700.16 (both insured persons)
        },
        "findings": [],
        "table_summary": "Insured Person's Premium Details",
    }
    merged = accumulate(
        {
            "page_outputs": [page_premium_partial],
            "table_output": table_out,
            "findings": [],
        },
        None,
    )["extraction"]

    # The whole-table premium (family total) overrides the partial page-local row.
    assert merged["annual_premium"] == 34526.14
