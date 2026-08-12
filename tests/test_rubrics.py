"""Tests for per-product rubrics + the three prompt builders."""

import json

import pytest

from policydecoder.graph.rubrics import (
    PRODUCTS,
    build_layman_prompt,
    build_table_analyzer_prompt,
    build_triage_prompt,
    load_rubric_file,
    rubric_rules_text,
)


@pytest.mark.parametrize("product", PRODUCTS)
def test_rubric_file_loads_and_validates(product):
    rubric = load_rubric_file(product)
    assert rubric["product"] == product
    assert rubric["version"] == 1
    assert rubric["required_fields"]
    assert rubric["rules"]
    for rule in rubric["rules"]:
        assert rule["id"]
        assert rule["check"]
        assert rule["severity"] in ("info", "warning", "alert")
        assert rule["explain_template"]
        assert rule["action_template"]
        assert rule["source"]


def test_rubric_rules_text_renders():
    rubric = load_rubric_file("HEALTH")
    text = rubric_rules_text(rubric)
    assert "co_pay" in text
    assert "threshold: 20" in text


def test_build_triage_prompt_includes_rules_and_schema():
    rubric = load_rubric_file("HEALTH")
    prompt = build_triage_prompt("HEALTH", rubric, "PAGE TEXT", 3, 10)
    assert "co_pay" in prompt
    assert "room_rent_cap" in prompt
    assert "sum_insured" in prompt
    assert "annual_premium" in prompt
    assert "PAGE 3 OF 10" in prompt
    assert "PAGE TEXT" in prompt


def test_build_table_analyzer_prompt_receives_full_tables():
    rubric = load_rubric_file("LIFE")
    tables = json.dumps([{"header": ["Year", "Surrender Value"], "rows": [[1, 50000]]}])
    prompt = build_table_analyzer_prompt("LIFE", rubric, tables)
    assert "surrender_value_table" in prompt
    assert "Year" in prompt  # the full table content is included


def test_build_layman_prompt_forbids_recomputation():
    rubric = load_rubric_file("LIFE")
    prompt = build_layman_prompt(
        "LIFE",
        rubric,
        {"policy_name": "X", "annual_premium": 50000},
        {"xirr": 0.03},
        [{"category": "xirr_below_benchmark", "what": "XIRR is 3%"}],
    )
    assert "NEVER do arithmetic" in prompt
    assert "do not recompute" in prompt.lower() or "never recompute" in prompt.lower()
    assert "xirr" in prompt


def test_health_rubric_has_ditto_musthaves():
    rubric = load_rubric_file("HEALTH")
    ids = {r["id"] for r in rubric["rules"]}
    for expected in (
        "co_pay",
        "room_rent_cap",
        "disease_sub_limits",
        "pre_post_hospitalization",
        "ped_waiting_period",
        "daycare_coverage",
        "restoration_benefit",
        "network_hospitals",
        "insurer_icr",
        "free_look",
    ):
        assert expected in ids


def test_life_rubric_has_charge_and_xirr_rules():
    rubric = load_rubric_file("LIFE")
    ids = {r["id"] for r in rubric["rules"]}
    for expected in (
        "xirr_below_benchmark",
        "premium_allocation_charge",
        "fund_management_charge",
        "surrender_loss",
        "product_vs_need",
        "free_look",
    ):
        assert expected in ids


def test_term_rubric_has_pure_term_check():
    rubric = load_rubric_file("TERM")
    ids = {r["id"] for r in rubric["rules"]}
    assert "endowment_disguised_as_term" in ids
