"""Graph node functions for the policy-decoder pipeline.

Each node wraps an existing agent or a deterministic port of the legacy
handler logic. Nodes only orchestrate; math stays in calculator.py /
health_calculator.py and LLM calls stay inside the agents/analyzer.

Agents are reached through runtime.context.agents (AgentContext).
"""

import json
from datetime import UTC, datetime

from langgraph.runtime import Runtime

from policydecoder.calculator import life_calc
from policydecoder.graph.state import AgentContext, GraphContext, PipelineState
from policydecoder.logging import get_logger

logger = get_logger("policydecoder.graph.nodes")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()[:19]


def _agents(runtime: Runtime[GraphContext]) -> AgentContext:
    """Return the AgentContext (required at runtime; mypy narrowing helper)."""
    if runtime.context.agents is None:
        raise RuntimeError("AgentContext is not configured on GraphContext")
    return runtime.context.agents


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def case_summary(state: PipelineState) -> str:
    """Port of CaseManager.get_summary_for_llm — compact JSON for prompts."""
    policy = state.get("policy_data") or {}
    analysis = state.get("analysis") or {}
    return json.dumps(
        {
            "state": state.get("case_state", "IDLE"),
            "policy": policy.get("policy_name"),
            "missold": analysis.get("is_likely_missold"),
            "completed": state.get("actions_completed", []),
            "pending": state.get("pending_actions", []),
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


async def media_route(state: PipelineState, runtime: Runtime[GraphContext]) -> dict:
    """Classify the document via the router agent.

    Chooses the extraction path: the rubric page-by-page dual-track when the
    caller opts in (use_rubric_triage=true, set by the live handler for
    multi-page docs), else the legacy extract path (default, preserves the
    existing behavior and tests).
    """
    router = _agents(runtime).router
    media_urls = state.get("media_urls") or []
    input_path = state.get("input_path")
    label, _confidence = await router.run(media_urls=media_urls, input_path=input_path)
    document_type = label if label in ("HEALTH", "LIFE") else "LIFE"

    use_rubric = bool(state.get("use_rubric_triage"))
    logger.info(
        "media_route decision: document_type=%s use_rubric_triage=%s input_path=%s → route=%s",
        document_type,
        use_rubric,
        bool(input_path),
        "rubric" if use_rubric else "extract",
    )
    return {
        "document_type": document_type,
        "route": "rubric" if use_rubric else "extract",
    }


async def text_intent(state: PipelineState, runtime: Runtime[GraphContext]) -> dict:
    """Classify the intent of a text-only message, with memory context."""
    analyzer = _agents(runtime).analyzer
    intent_result = analyzer.classify_intent(
        message_text=state.get("text", ""),
        case_state=state.get("case_state", "IDLE"),
        case_summary=case_summary(state),
    )
    intent = intent_result.get("intent", "UNKNOWN")
    confidence = intent_result.get("confidence", 0.0)
    if confidence < 0.7 and intent != "UNKNOWN":
        return {"intent": "UNKNOWN", "intent_confidence": confidence}
    return {"intent": intent, "intent_confidence": confidence}


def route_start(state: PipelineState) -> dict:
    """Route node: write which branch to take into state."""
    if state.get("media_urls") or state.get("input_path"):
        return {"route": "media_route"}
    return {"route": "text_intent"}


def route_path(state: PipelineState) -> str:
    """Conditional-edge path function: return the target node name."""
    return state.get("route", "text_intent")


# ---------------------------------------------------------------------------
# Media pipeline
# ---------------------------------------------------------------------------


async def extract(state: PipelineState, runtime: Runtime[GraphContext]) -> dict:
    """Extract policy data via the extractor agent (with short-circuit)."""
    extractor = _agents(runtime).extractor_agent
    result = await extractor.run(
        media_urls=state.get("media_urls") or [],
        document_type=state.get("document_type", "LIFE"),
        input_path=state.get("input_path"),
    )
    return {
        "extraction": result.get("data", {}),
        "missing": result.get("missing", []),
        "short_circuited": bool(result.get("short_circuited")),
    }


async def research(state: PipelineState, runtime: Runtime[GraphContext]) -> dict:
    """Fetch whitelisted research findings via the researcher agent."""
    researcher = _agents(runtime).researcher
    document_type = state.get("document_type", "LIFE")
    topic = "how_to_choose_health" if document_type == "HEALTH" else "how_to_choose_term"
    findings = await researcher.run(topic=topic)
    return {"findings": findings}


def after_extract(state: PipelineState) -> str:
    """Branch after extraction: short-circuit → format_short_circuit, else analyst."""
    if state.get("short_circuited"):
        return "format_short_circuit"
    return "analyst"


async def gate(state: PipelineState, runtime: Runtime[GraphContext]) -> dict:
    """Fan-in barrier after (extract ∥ research): no-op, just merges state."""
    return {}


async def analyst(state: PipelineState, runtime: Runtime[GraphContext]) -> dict:
    """Health or life analyst, based on document_type. Math stays deterministic."""
    extraction = state.get("extraction") or {}
    findings = state.get("findings") or []
    document_type = state.get("document_type", "LIFE")
    memory_context = state.get("memory_context", "")

    if document_type == "HEALTH":
        analysis = await _agents(runtime).health_analyst.run(
            extraction=extraction, findings=findings
        )
    else:
        user_age = state.get("user_age")
        calc = life_calc(extraction, user_age=user_age)
        analysis = await _agents(runtime).life_analyst.run(
            extraction=extraction, calc_results=calc, findings=findings
        )
        analysis["_calc_results"] = calc

    if memory_context:
        analysis["_memory_context"] = memory_context
    return {"analysis": analysis, "calc_results": calc if document_type != "HEALTH" else {}}


async def format_short_circuit(state: PipelineState, runtime: Runtime[GraphContext]) -> dict:
    return {
        "reply": (
            "I need the full policy document — you only uploaded a partial document. "
            "Please share the complete policy pages."
        ),
    }


async def format_report(state: PipelineState, runtime: Runtime[GraphContext]) -> dict:
    """Port of handler._format_supervisor_report."""
    data = state.get("extraction") or {}
    analysis = state.get("analysis") or {}
    parts = ["Here's my honest take:\n"]
    if data.get("policy_name"):
        parts.append(f"Policy: {data['policy_name']}")
    if data.get("sum_insured"):
        parts.append(f"Sum insured: ₹{data['sum_insured']:,.0f}")
    if data.get("annual_premium"):
        parts.append(f"Annual premium: ₹{data['annual_premium']:,.0f}")
    if analysis.get("summary"):
        parts.append(f"\n{analysis['summary']}")
    if analysis.get("red_flags"):
        parts.append("\nRed flags:")
        for flag in analysis["red_flags"]:
            parts.append(f"  - {flag}")
    parts.append(
        "\nBased on IRDAI FY2024-25 public data and live research where available. "
        "This is an honest assessment, not a recommendation to buy or cancel."
    )
    return {"reply": "\n".join(parts)}


# ---------------------------------------------------------------------------
# Text flow (replaces CaseState state machine)
# ---------------------------------------------------------------------------


def route_intent(state: PipelineState) -> str:
    """Branch by intent for the text flow."""
    intent = state.get("intent", "UNKNOWN")
    if intent == "STATUS_CHECK":
        return "status_reply"
    if intent == "CONFIRM_ACTION":
        return "confirm_action"
    return "text_answer"


async def text_answer(state: PipelineState, runtime: Runtime[GraphContext]) -> dict:
    """Answer text intents. Collects missing info, asks for age when needed."""
    intent = state.get("intent", "UNKNOWN")
    text = state.get("text", "")

    if intent in ("NEW_POLICY", "QUESTION") and not state.get("policy_data"):
        return {
            "reply": (
                "I'd like to analyze your policy. Could you either:\n"
                "1. Send a photo of the policy document (the first page with details), or\n"
                "2. Tell me: policy name, annual premium, term, and sum assured\n\n"
                "A photo is better — I can read the charges and surrender table from it."
            )
        }

    # INFO_RESPONSE: try to capture age from a bare number
    if intent == "INFO_RESPONSE" and text.isdigit():
        age = int(text)
        if 18 <= age <= 80:
            state["user_age"] = age
            if state.get("policy_data"):
                return await _run_analysis(state, runtime)
            return {"reply": f"Thanks — age {age} noted. Send me your policy document to analyze."}
        return {"reply": "That age doesn't look right. Could you tell me your age (18-80)?"}

    if intent == "INFO_RESPONSE" and state.get("policy_data") is None:
        return {"reply": "I need your age to run the comparison. Just type the number (e.g., 32)."}

    return {"reply": "I can help with your insurance policy. Send a photo or PDF to get started."}


async def _run_analysis(state: PipelineState, runtime: Runtime[GraphContext]) -> dict:
    """Deterministic life analysis (ported from handler._run_analysis)."""
    data = state.get("policy_data") or {}
    annual_premium = float(data.get("annual_premium", 0))
    policy_term = int(data.get("policy_term_years", 0))
    maturity_value = float(
        data.get("maturity_value_at_8pct") or data.get("maturity_value_at_4pct") or 0
    )

    if not all([annual_premium, policy_term, maturity_value]):
        return {
            "reply": (
                "I don't have enough numbers to run the analysis. Could you share: "
                "annual premium, policy term, and the maturity value from the benefit "
                "illustration (the 8% column)?"
            )
        }

    user_age = state.get("user_age") or 30
    calc = life_calc(data, user_age=user_age)
    analysis = await _agents(runtime).life_analyst.run(
        extraction=data, calc_results=calc, findings=[]
    )
    analysis["_calc_results"] = calc

    reply = _format_life_report(data, calc, analysis)
    return {"analysis": analysis, "calc_results": calc, "reply": reply}


def _format_life_report(data: dict, calc: dict, analysis: dict) -> str:
    """Port of handler._run_analysis report formatting."""
    xirr_pct = round(calc.get("xirr", 0) * 100, 1)
    parts = [
        f"Analysis of your {data.get('policy_name', 'policy')}:",
        "",
        f"Your policy returns: {xirr_pct}% per year",
        "A term plan + SIP would return: ~11% per year",
        "",
        f"After {data.get('policy_term_years', '?')} years:",
        f"  Your policy gives: {calc.get('policy_maturity', 0)}",
        f"  Term + SIP gives: {calc.get('term_sip_value', 0)}",
        f"  You're losing: {calc.get('opportunity_cost', 0)}",
        "",
    ]
    if analysis.get("summary"):
        parts.append(analysis["summary"])
    if analysis.get("key_findings"):
        parts.append("")
        for finding in analysis["key_findings"]:
            parts.append(f"  - {finding}")
    if analysis.get("recommended_action") == "free_look_cancel":
        parts.append(
            f"Good news: you're within the {calc.get('free_look_days', 15)}-day free-look period. "
            "You can cancel and get a full refund. Want me to draft the cancellation letter?"
        )
    elif analysis.get("is_likely_missold"):
        parts.append(
            "This looks like a mis-sold policy. I can draft a complaint letter "
            "to the insurer. Want me to?"
        )
    else:
        parts.append(
            "This policy doesn't show obvious signs of mis-selling. "
            "But the returns are still lower than alternatives. "
            "Want me to explain the numbers in more detail?"
        )
    return "\n".join(parts)


async def status_reply(state: PipelineState, runtime: Runtime[GraphContext]) -> dict:
    """Port of CaseManager.get_timeline from graph state."""
    lines = [f"Case status: {state.get('case_state', 'IDLE')}"]
    policy = state.get("policy_data") or {}
    analysis = state.get("analysis") or {}
    if policy.get("policy_name"):
        lines.append(f"Policy: {policy['policy_name']}")
    calc = state.get("calc_results") or {}
    if calc.get("xirr"):
        lines.append(f"Policy XIRR: {calc['xirr'] * 100:.1f}%")
    if analysis.get("is_likely_missold") is not None:
        verdict = "Yes" if analysis["is_likely_missold"] else "No"
        lines.append(f"Likely mis-sold: {verdict}")
    if state.get("actions_completed"):
        lines.append("")
        lines.append("Completed:")
        for a in state["actions_completed"]:
            lines.append(f"  [done] {a.get('action')}")
    if state.get("pending_actions"):
        lines.append("")
        lines.append("Pending:")
        for a in state["pending_actions"]:
            lines.append(f"  [pending] {a.get('action')}")
    return {"reply": "\n".join(lines)}


async def confirm_action(state: PipelineState, runtime: Runtime[GraphContext]) -> dict:
    """Port of handler._handle_analyzed_confirm — draft the letter."""
    analysis = state.get("analysis") or {}
    data = state.get("policy_data") or {}
    drafter = _agents(runtime).letter_drafter

    if analysis.get("recommended_action") == "free_look_cancel":
        letter = await drafter.run(letter_type="free_look", policy_data=data, analysis=analysis)
    else:
        letter = await drafter.run(letter_type="complaint", policy_data=data, analysis=analysis)

    return {
        "reply": (
            f"Here's your letter:\n\n---\n\n{letter}\n\n---\n\nReply CONFIRM once you've sent it."
        ),
        "letter": letter,
    }
