"""Dual-track page-by-page triage for 20+ page policies.

Track A (text): parallel per-page triage — each page LLM-checked against the
product rubric, returns partial fields + findings.
Track B (tables): ONE global table-analyzer call over the WHOLE tables JSON
(Docling/TableFormer stitches tables across page breaks structurally), so
cross-page tables (surrender schedules, premium projections) are never
hallucinated by a page-local model.

Both tracks converge in `accumulate`, then deterministic calculators run on
the merged fields, then the layman writer produces the plain-language verdict.

Rubrics are loaded ONCE by `prepare_triage` into graph state — the parallel
triage nodes read from state (zero repeat DB queries for static data).
"""

import json
from typing import Any

from langgraph.runtime import Runtime

from policydecoder.graph.prompt_store import PromptStore
from policydecoder.graph.rubrics import (
    build_layman_prompt,
    build_table_analyzer_prompt,
    build_triage_prompt,
)
from policydecoder.graph.state import GraphContext, PipelineState
from policydecoder.logging import get_logger
from policydecoder.schemas import (
    LaymanVerdict,
    PageTriageOutput,
    TableAnalysisOutput,
)

logger = get_logger("policydecoder.graph.triage")


async def prepare_triage(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """Load the product rubric ONCE into graph state (no per-page store reads)."""
    product = state.get("document_type", "LIFE")
    store = runtime.store
    rubric = None
    if store is not None:
        try:
            ps = PromptStore(store)
            rubric = await ps.load_rubric(product)
        except Exception as e:
            logger.warning("Failed to load rubric for %s from store: %s", product, e)
    if rubric is None:
        from policydecoder.graph.rubrics import load_rubric_file

        rubric = load_rubric_file(product)  # fallback to checked-in file
    return {"rubric": rubric, "document_type": product}


def _llm_generate(
    runtime: Runtime[GraphContext], system: str, user: str, timeout: float = 20.0
) -> str:
    """Single sync LLM call with tracing. Never raises (returns "" on failure)."""
    from policydecoder.graph.memory import _llm_generate as _mem_gen

    agents = runtime.context.agents
    if agents is None or agents.llm is None:
        return ""
    return _mem_gen(agents.llm, system, user, timeout=timeout)


async def triage_page(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """Track A: one LLM call per page against the rubric (from state)."""
    rubric = state.get("rubric")
    if not rubric:
        return {"page_outputs": []}
    raw_page_no = state.get("_triage_page_no", 1)
    page_no = int(raw_page_no) if isinstance(raw_page_no, int | str) else 1
    pages = state.get("pages_markdown", []) or []
    total = len(pages) or int(state.get("page_count", 1) or 1)
    if not pages:
        return {"page_outputs": []}
    page_md = pages[page_no - 1] if page_no <= len(pages) else ""

    product = state.get("document_type", "LIFE")
    prompt = build_triage_prompt(product, rubric, page_md, page_no, total)
    content = _llm_generate(runtime, "You are an insurance policy page reviewer.", prompt)

    from policydecoder.extractor import parse_json_response

    parsed = parse_json_response(content)
    try:
        out = PageTriageOutput.model_validate(parsed)
    except Exception as e:
        logger.warning("Page %d triage output invalid, dropped: %s", page_no, e)
        return {"page_outputs": []}
    return {"page_outputs": [out.model_dump()]}


async def table_analyzer(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """Track B: ONE call over the WHOLE tables JSON (cross-page tables)."""
    rubric = state.get("rubric")
    tables_json = state.get("tables_json", [])
    if not rubric or not tables_json:
        return {"table_output": None}
    product = state.get("document_type", "LIFE")
    prompt = build_table_analyzer_prompt(
        product, rubric, json.dumps(tables_json, ensure_ascii=False)[:20000]
    )
    content = _llm_generate(runtime, "You are an insurance policy table reviewer.", prompt)

    from policydecoder.extractor import parse_json_response

    parsed = parse_json_response(content)
    try:
        out = TableAnalysisOutput.model_validate(parsed)
    except Exception as e:
        logger.warning("Table analysis output invalid, dropped: %s", e)
        return {"table_output": None}
    return {"table_output": out.model_dump()}


# Fields that NEED whole-table context (cross-page tables). The global table
# track is authoritative for these — a page-local model seeing column-less
# continuation rows must NOT override the stitched-table values.
_TABLE_AUTHORITATIVE_FIELDS = {
    "surrender_value_table",
    "maturity_value_at_4pct",
    "maturity_value_at_8pct",
    "premium_term_years",
    "policy_term_years",
    "sum_assured",
    "sum_insured",
    "annual_premium",  # family-floater premium tables span pages; page-local triage
    # only sees one insured person's row (e.g. ₹25,826 of a ₹34,526 family premium).
    "sub_limits",
    "waiting_periods",
    "charges",
}


def accumulate(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """Merge Track A (page fields) + Track B (table fields).

    Page fields fill first-non-null. Table fields then fill remaining gaps AND
    override for table-authoritative keys — because the table track saw the
    WHOLE stitched table, while a page-local model may have hallucinated from
    column-less continuation rows (the cross-page fragmentation flaw).
    """
    merged: dict[str, Any] = {}
    page_outputs = state.get("page_outputs", []) or []
    for out in page_outputs:
        for key, value in (out.get("fields") or {}).items():
            if value is not None and not merged.get(key):
                merged[key] = value

    table_out = state.get("table_output")
    if table_out:
        for key, value in (table_out.get("fields") or {}).items():
            if value is None:
                continue
            if key in _TABLE_AUTHORITATIVE_FIELDS or not merged.get(key):
                merged[key] = value

    findings: list[dict[str, Any]] = list(state.get("findings", []) or [])
    for out in page_outputs:
        findings.extend(out.get("findings") or [])
    if table_out:
        findings.extend(table_out.get("findings") or [])

    return {"extraction": merged, "findings": findings}


def has_required(state: PipelineState) -> str:
    """Branch: all required fields present → deterministic_calc, else targeted re-read."""
    rubric = state.get("rubric") or {}
    required = rubric.get("required_fields", [])
    extraction = state.get("extraction") or {}
    missing = [f for f in required if not extraction.get(f)]
    if missing:
        return "targeted_re_read"
    return "deterministic_calc"


async def targeted_re_read(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """Re-read ONLY the pages most likely to hold the missing fields (keyword-scored).

    Never re-reads the whole document — this is the short-circuit evolution: only
    the genuinely-missing field's likely pages get one more LLM pass.
    """
    extraction = dict(state.get("extraction") or {})
    rubric = state.get("rubric") or {}
    required = rubric.get("required_fields", [])
    missing = [f for f in required if not extraction.get(f)]
    if not missing:
        return {"extraction": extraction}

    pages = state.get("pages_markdown", []) or []
    keywords = {
        "annual_premium": ["premium", "premium amount", "total premium", "payable"],
        "sum_insured": ["sum insured", "sum assured", "cover", "benefit"],
        "sum_assured": ["sum assured", "sum insured", "death benefit", "cover"],
        "policy_term_years": ["policy term", "term", "years", "maturity"],
        "policy_name": ["policy name", "plan name", "policy no"],
    }

    def score(page_md: str) -> int:
        # Score against ALL missing fields, not just the first — a page holding
        # the premium is still a re-read candidate even if sum_insured is also missing.
        return sum(
            1 for f in missing for kw in keywords.get(f, []) if kw.lower() in page_md.lower()
        )

    scored = sorted(enumerate(pages), key=lambda x: score(x[1]), reverse=True)
    candidate_pages = [i for i, _ in scored[:3] if score(pages[i]) > 0]
    if not candidate_pages:
        return {"extraction": extraction}  # genuinely absent → keep partial, short-circuit

    for page_idx in candidate_pages:
        page_no = page_idx + 1
        rubric_ = state.get("rubric") or {}
        product = state.get("document_type", "LIFE")
        prompt = build_triage_prompt(product, rubric_, pages[page_idx], page_no, len(pages))
        content = _llm_generate(runtime, "You are an insurance policy page reviewer.", prompt)
        from policydecoder.extractor import parse_json_response

        parsed = parse_json_response(content)
        try:
            out = PageTriageOutput.model_validate(parsed)
        except Exception as e:
            logger.warning("Targeted re-read page %d invalid: %s", page_no, e)
            continue
        for key, value in (out.fields or {}).items():
            if value is not None and not extraction.get(key):
                extraction[key] = value
        if not [f for f in missing if not extraction.get(f)]:
            break

    return {"extraction": extraction}


def _sanitize_extraction(extraction: dict[str, Any], document_type: str) -> dict[str, Any]:
    """Validate the merged fields against the product schema before the calculators.

    The triage LLM's `fields` is untyped JSON — a wrong type (e.g. `restoration:
    true` as a bool instead of a string) must be coerced/rejected here so a
    hallucinated value never crashes or corrupts the deterministic calculators.
    Coercion failure → the field is dropped (treated as absent), which the
    required-field check already handles.
    """
    from policydecoder.schemas import HealthPolicyExtraction, LifePolicyExtraction

    model = HealthPolicyExtraction if document_type == "HEALTH" else LifePolicyExtraction
    try:
        return model.model_validate(extraction).model_dump()
    except Exception as e:
        logger.warning("Extraction schema validation failed, sanitizing: %s", e)
        # Fall back: validate each field against the already-cleaned fields plus
        # itself, so one bad field never sinks a good sibling.
        cleaned: dict[str, Any] = {}
        for key, value in extraction.items():
            if key not in model.model_fields:
                cleaned[key] = value  # extra keys (insurer, findings) pass through
                continue
            try:
                cleaned[key] = model.model_validate({**cleaned, key: value}).model_dump()[key]
            except Exception:
                logger.warning("Dropping invalid field %s (type %s)", key, type(value).__name__)
        return cleaned


def deterministic_calc(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """Run the pure calculators on the merged fields. The LLM never does math."""
    from policydecoder.calculator import life_calc
    from policydecoder.health_calculator import score_health_policy
    from policydecoder.insurer_data import get_insurer_metrics

    extraction = state.get("extraction") or {}
    document_type = state.get("document_type", "LIFE")
    user_age = state.get("user_age")

    extraction = _sanitize_extraction(extraction, document_type)

    if document_type == "HEALTH":
        insurer = extraction.get("insurer")
        benchmark = get_insurer_metrics(insurer) if insurer else None
        report = score_health_policy(extraction, benchmark, {})
        calc = {
            "overall": report.get("overall"),
            "policy_flags": report.get("policy_flags", []),
            "insurer_metrics": report.get("insurer_metrics", {}),
        }
    else:
        calc = life_calc(extraction, user_age=user_age)

    return {"calc_results": calc, "extraction": extraction}


async def layman_writer(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """Second LLM: merged fields + calc results + findings → plain-language verdict.

    Rephrases ONLY — explicitly forbidden from recomputing anything.
    """
    rubric = state.get("rubric") or {}
    product = state.get("document_type", "LIFE")
    extraction = state.get("extraction") or {}
    calc = state.get("calc_results") or {}
    findings = state.get("findings", []) or []

    prompt = build_layman_prompt(product, rubric, extraction, calc, findings)
    content = _llm_generate(runtime, "You are a plain-language insurance explainer.", prompt)

    from policydecoder.extractor import parse_json_response

    parsed = parse_json_response(content)
    try:
        verdict = LaymanVerdict.model_validate(parsed)
    except Exception as e:
        logger.warning("Layman verdict invalid, falling back to calc overall: %s", e)
        overall = calc.get("overall")
        if overall not in ("GOOD", "REVIEW", "ALERT"):
            if extraction.get("xirr") is not None and float(extraction.get("xirr", 0) or 0) < 0.05:
                overall = "ALERT"
            else:
                overall = "REVIEW"
        verdict = LaymanVerdict(
            summary="Analysis completed. See items.",
            items=[],
            verdict=overall,  # type: ignore[arg-type]
        )

    return {"layman_verdict": verdict.model_dump()}


def format_layman_report(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """Format the LaymanVerdict into a user reply (existing formatter style)."""
    verdict = state.get("layman_verdict") or {}
    extraction = state.get("extraction") or {}
    parts = ["Here's my honest take:\n"]
    if extraction.get("policy_name"):
        parts.append(f"Policy: {extraction['policy_name']}")
    if extraction.get("sum_insured"):
        parts.append(f"Sum insured: ₹{extraction['sum_insured']:,.0f}")
    if extraction.get("annual_premium"):
        parts.append(f"Annual premium: ₹{extraction['annual_premium']:,.0f}")

    if verdict.get("summary"):
        parts.append(f"\n{verdict['summary']}")

    items = verdict.get("items", []) or []
    if items:
        parts.append("\nWhat to know:")
        for it in items:
            sev = {"info": "ℹ️", "warning": "⚠️", "alert": "🔴"}.get(it.get("severity"), "•")
            parts.append(f"  {sev} {it.get('what', '')}")
            if it.get("why_it_matters"):
                parts.append(f"     {it['why_it_matters']}")
            if it.get("what_to_do"):
                parts.append(f"     → {it['what_to_do']}")

    parts.append(
        "\nBased on IRDAI FY2024-25 public data and gold-standard review checklists. "
        "This is an honest assessment, not a recommendation to buy or cancel."
    )
    return {"reply": "\n".join(parts)}
