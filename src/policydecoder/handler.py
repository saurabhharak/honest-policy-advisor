"""The one on_message handler. Routes email and Telegram messages.

Never branches on channel type. The SDK handles routing via message.reply().
"""

import json
from datetime import UTC, date, datetime

from caspian_sdk import CommClient

from policydecoder.analyzer import PolicyAnalyzer
from policydecoder.calculator import (
    estimate_term_cost,
    format_inr,
    opportunity_cost,
    policy_cash_flows,
    surrender_loss,
    term_plus_sip_value,
    xirr,
)
from policydecoder.case_manager import CaseState, case_manager
from policydecoder.email_link import build_gmail_compose_url
from policydecoder.extractor import PolicyExtractor
from policydecoder.guardrails import (
    GuardrailValidationError,
    validate_policy_fields,
    validate_user_input,
)
from policydecoder.health_calculator import score_health_policy
from policydecoder.insurer_data import get_insurer_metrics
from policydecoder.router import HEALTH, classify_document

WELCOME_MESSAGE = """I read insurance policies and tell you if you were mis-sold.

Send me a photo or PDF of your policy document and I'll:
1. Extract the key details (premium, charges, surrender values)
2. Calculate what it's actually returning vs. what you could get elsewhere
3. Draft a complaint letter if it was mis-sold

You can send the policy as a photo (Telegram) or PDF attachment (email)."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()[:19]


def handle(
    client: CommClient,
    message,
    extractor: PolicyExtractor,
    analyzer: PolicyAnalyzer,
):
    """Single handler for all channels."""
    conversation_id = message.conversation_id
    sender = (message.sender or {}).get("address", "anonymous")
    text = (message.text or "").strip()
    media = getattr(message, "media", []) or []

    # Media (policy PDF photo) takes priority
    if media:
        _handle_media(client, message, extractor, analyzer, conversation_id, sender)
        return

    if not text:
        message.reply("Send me a photo or PDF of your insurance policy and I'll analyze it.")
        return

    # Input rail: block prompt-injection / jailbreak attempts on user text.
    try:
        validate_user_input(text)
    except GuardrailValidationError as e:
        message.reply(e.user_message)
        return

    case = case_manager.get_or_create(conversation_id, sender)

    # Classify intent
    intent_result = analyzer.classify_intent(
        message_text=text,
        case_state=case.state.value,
        case_summary=case_manager.get_summary_for_llm(conversation_id),
    )
    intent = intent_result.get("intent", "UNKNOWN")
    confidence = intent_result.get("confidence", 0.0)

    if confidence < 0.7 and intent != "UNKNOWN":
        message.reply(
            "I want to help. Can you tell me more? For example, share your policy document "
            "or ask me a question about your insurance."
        )
        return

    # Route to state handler
    _STATE_ROUTER.get(case.state, {}).get(intent, _handle_unknown)(
        client, message, case, extractor, analyzer, intent_result
    )


def _handle_media(client, message, extractor, analyzer, conversation_id, sender):
    """Process policy document photos/PDFs — routed by document type."""
    media_urls = [m.get("url") for m in message.media if m.get("url")]
    if not media_urls:
        message.reply("I received an attachment but couldn't read it. Could you try again?")
        return

    case = case_manager.get_or_create(conversation_id, sender)
    message.typing()

    # Router: classify the document so we extract with the right schema.
    label, confidence = classify_document(
        extractor.llm,
        media_urls,
        model=extractor.vision_model,
        fallback_text="",
    )

    if label == HEALTH:
        _handle_health_media(message, extractor, analyzer, media_urls, case, confidence)
    else:
        _handle_life_media(message, extractor, analyzer, media_urls, case)


def _handle_health_media(message, extractor, analyzer, media_urls, case, confidence):
    """Health policy path: health schema → health calculator → health analysis."""
    data = extractor.extract_health(media_urls)

    if not data:
        message.reply(
            "I couldn't read the health policy document. Could you try:\n"
            "1. A clearer photo (good lighting, flat surface)\n"
            "2. The page with the sum insured, premium, and room rent details\n"
            "3. Or just type the details: sum insured, annual premium, insurer"
        )
        return

    # Input rail: block prompt-injection embedded in the policy document.
    try:
        validate_policy_fields(data)
    except GuardrailValidationError as e:
        message.reply(e.user_message)
        return

    # Score against the insurer benchmark
    insurer_name = data.get("insurer")
    benchmark = get_insurer_metrics(insurer_name)
    report = score_health_policy(data, benchmark, {})

    case_manager.update_case(case.case_id, policy_data=data)

    # Let the LLM write the honest verdict from the computed flags
    analysis = analyzer.analyze_health_policy(
        extracted_json=json.dumps(data, ensure_ascii=False),
        policy_flags="\n".join(f"- {f}" for f in report["policy_flags"]) or "None",
        insurer_metrics=json.dumps(report["insurer_metrics"], ensure_ascii=False),
        overall=report["overall"],
    )
    case_manager.update_case(case.case_id, analysis_result=analysis)

    reply = _format_health_report(data, report, analysis, confidence)
    message.reply(reply)


def _format_health_report(data, report, analysis, confidence) -> str:
    """Format the health policy report for the user."""
    parts = ["Here's my honest take on your health policy:\n"]

    # What we extracted
    summary_bits = []
    if data.get("policy_name"):
        summary_bits.append(f"Policy: {data['policy_name']}")
    if data.get("insurer"):
        summary_bits.append(f"Insurer: {data['insurer']}")
    if data.get("sum_insured"):
        summary_bits.append(f"Sum insured: ₹{data['sum_insured']:,.0f}")
    if data.get("annual_premium"):
        summary_bits.append(f"Annual premium: ₹{data['annual_premium']:,.0f}")
    if summary_bits:
        parts.append("\n".join(summary_bits))

    # Flags (deterministic)
    if report["policy_flags"]:
        parts.append("\nWhat to check:")
        for flag in report["policy_flags"]:
            parts.append(f"  ⚠ {flag}")
    else:
        parts.append("\nNo major red flags in the policy terms I could extract.")

    # Insurer benchmark
    bench = report["insurer_metrics"]
    if bench.get("icr_status") != "no_data":
        icr = bench.get("icr_value")
        parts.append(
            f"\nInsurer track record (IRDAI FY2024-25): "
            f"{bench['insurer']} — incurred claim ratio {icr:.1f}% "
            f"({bench['icr_status']})."
        )
    else:
        parts.append("\nNo IRDAI benchmark data found for this insurer yet.")

    # Verdict
    verdict_emoji = {"GOOD": "✅", "REVIEW": "🟡", "ALERT": "🔴"}.get(report["overall"], "ℹ️")
    verdict_line = {
        "GOOD": "This policy looks genuinely fine on the terms I could check.",
        "REVIEW": "This policy has a few things worth reviewing before you commit.",
        "ALERT": "This policy has serious red flags. I'd be cautious here.",
    }.get(report["overall"], "")
    parts.append(f"\n{verdict_emoji} {verdict_line}")

    if analysis.get("summary"):
        parts.append(f"\n{analysis['summary']}")

    if analysis.get("red_flags"):
        parts.append("\nRed flags:")
        for flag in analysis["red_flags"]:
            parts.append(f"  - {flag}")

    if analysis.get("honest_reassurance"):
        parts.append(f"\nWhat's fine: {analysis['honest_reassurance']}")

    if confidence < 0.6:
        parts.append(
            "\nNote: I wasn't fully sure this is a health policy — "
            "if this is a life policy, let me know and I'll re-check."
        )

    parts.append(
        "\nBased on IRDAI FY2024-25 public data. "
        "This is an honest assessment, not a recommendation to buy or cancel."
    )
    return "\n".join(parts)


def _handle_life_media(message, extractor, analyzer, media_urls, case):
    """Life/ULIP/term policy path: the existing life analysis flow."""
    # Extract policy data from the image(s)
    if len(media_urls) == 1:
        data = extractor.extract_from_image(media_urls[0])
    else:
        data = extractor.extract_from_images(media_urls)

    missing = extractor.validate_extraction(data)

    if not data:
        message.reply(
            "I couldn't read the policy document. Could you try:\n"
            "1. A clearer photo (good lighting, flat surface)\n"
            "2. The first page of the policy (has the key details)\n"
            "3. Or just type the details: policy name, annual premium, term, sum assured"
        )
        return

    # Input rail: block prompt-injection embedded in the policy document.
    try:
        validate_policy_fields(data)
    except GuardrailValidationError as e:
        message.reply(e.user_message)
        return

    # Store what we extracted
    case_manager.update_case(case.case_id, policy_data=data)

    # Confirm what we found
    parts = []
    if data.get("policy_name"):
        parts.append(f"Policy: {data['policy_name']}")
    if data.get("insurer"):
        parts.append(f"Insurer: {data['insurer']}")
    if data.get("annual_premium"):
        parts.append(f"Annual premium: ₹{data['annual_premium']:,.0f}")
    if data.get("policy_term_years"):
        parts.append(f"Term: {data['policy_term_years']} years")
    if data.get("sum_assured"):
        parts.append(f"Sum assured: ₹{data['sum_assured']:,.0f}")
    if data.get("policy_type"):
        parts.append(f"Type: {data['policy_type'].replace('_', ' ').title()}")

    if parts:
        reply = "I read your policy. Here's what I found:\n\n" + "\n".join(parts)
    else:
        reply = "I received the document but couldn't extract the details clearly."

    if missing:
        reply += f"\n\nI still need: {', '.join(missing)}."
        if "policy_name" in missing:
            reply += "\nWhat's the policy name? (e.g., LIC Jeevan Anand, HDFC Click 2 Invest)"
        elif "annual_premium" in missing:
            reply += "\nWhat's the annual premium amount?"
        elif "policy_term_years" in missing:
            reply += "\nHow many years is the policy for?"
        elif "sum_assured" in missing:
            reply += "\nWhat's the sum assured (the cover amount)?"
        message.reply(reply)
        return

    reply += "\n\nI'm analyzing this now. One question: how old are you? (I need this to estimate what a term plan would cost you.)"
    message.reply(reply)
    case_manager.advance_state(case.case_id, CaseState.POLICY_RECEIVED)


def _run_analysis(client, message, case, analyzer):
    """Run the full analysis pipeline: calculate → analyze → report."""
    data = case.policy_data
    case_manager.update_case(case.case_id, message_count=case.message_count)

    # Build cash flows from extracted data
    annual_premium = float(data.get("annual_premium", 0))
    premium_term = int(data.get("premium_term_years") or data.get("policy_term_years", 0))
    policy_term = int(data.get("policy_term_years", 0))
    sum_assured = float(data.get("sum_assured", 0))

    # Use 8% benefit illustration as the "official" maturity value
    maturity_value = float(
        data.get("maturity_value_at_8pct") or data.get("maturity_value_at_4pct") or 0
    )

    if not all([annual_premium, policy_term, maturity_value]):
        message.reply(
            "I don't have enough numbers to run the analysis. "
            "Could you share: annual premium, policy term, and the maturity value "
            "from the benefit illustration (the 8% column)?"
        )
        return

    # Calculate XIRR of the policy
    start = date.today()
    flows = policy_cash_flows(annual_premium, premium_term, policy_term, maturity_value, start)
    try:
        policy_xirr = xirr(flows)
    except ValueError as e:
        message.reply(
            f"I couldn't calculate the returns — {e}. Could you double-check the numbers?"
        )
        return

    # Calculate term + SIP alternative
    user_age = case.user_age or 30
    term_cost = estimate_term_cost(user_age, sum_assured)
    sip_value = term_plus_sip_value(annual_premium, term_cost, policy_term)
    opp_cost = opportunity_cost(maturity_value, sip_value)

    # Surrender analysis
    policy_start = data.get("policy_start_date", "")
    days_since = (date.today() - date.fromisoformat(policy_start)).days if policy_start else 0
    premiums_paid = annual_premium * min(days_since // 365, premium_term) if days_since else 0
    free_look_days = int(data.get("free_look_period_days") or 15)

    # Try to estimate current surrender value
    current_surrender = premiums_paid * 0.3 if premiums_paid > 0 else 0
    sur_loss = surrender_loss(premiums_paid, current_surrender)

    # Store calculation results
    calc_results = {
        "xirr": policy_xirr,
        "term_sip_value": sip_value,
        "policy_maturity": maturity_value,
        "opportunity_cost": opp_cost,
        "term_cost": term_cost,
        "premiums_paid": premiums_paid,
        "surrender_value": current_surrender,
        "surrender_loss": sur_loss,
        "days_since_purchase": days_since,
        "free_look_days": free_look_days,
    }
    case_manager.update_case(case.case_id, calculation_results=calc_results)

    # Run LLM analysis
    analysis = analyzer.analyze_policy(
        extracted_json=json.dumps(data, ensure_ascii=False),
        policy_xirr=policy_xirr,
        term_sip_value=sip_value,
        policy_maturity=maturity_value,
        opportunity_cost=opp_cost,
        term_cost=term_cost,
        premiums_paid=premiums_paid,
        surrender_value=current_surrender,
        surrender_loss=sur_loss,
        user_age=user_age,
        days_since_purchase=days_since,
        free_look_days=free_look_days,
    )
    case_manager.update_case(case.case_id, analysis_result=analysis)

    # Build the report
    xirr_pct = round(policy_xirr * 100, 1)
    report_parts = [
        f"Analysis of your {data.get('policy_name', 'policy')}:",
        "",
        f"Your policy returns: {xirr_pct}% per year",
        "A term plan + SIP would return: ~11% per year",
        "",
        f"After {policy_term} years:",
        f"  Your policy gives: {format_inr(maturity_value)}",
        f"  Term + SIP gives: {format_inr(sip_value)}",
        f"  You're losing: {format_inr(opp_cost)}",
        "",
    ]

    if analysis.get("summary"):
        report_parts.append(analysis["summary"])

    if analysis.get("key_findings"):
        report_parts.append("")
        for finding in analysis["key_findings"]:
            report_parts.append(f"  - {finding}")

    report_parts.append("")
    if analysis.get("recommended_action") == "free_look_cancel":
        report_parts.append(
            f"Good news: you're within the {free_look_days}-day free-look period. "
            "You can cancel and get a full refund. Want me to draft the cancellation letter?"
        )
    elif analysis.get("is_likely_missold"):
        report_parts.append(
            "This looks like a mis-sold policy. I can draft a complaint letter "
            "to the insurer. Want me to?"
        )
    else:
        report_parts.append(
            "This policy doesn't show obvious signs of mis-selling. "
            "But the returns are still lower than alternatives. "
            "Want me to explain the numbers in more detail?"
        )

    message.reply("\n".join(report_parts))
    case_manager.advance_state(case.case_id, CaseState.ANALYZED)
    case_manager.add_action(case.case_id, "Draft complaint letter", _now_iso())


def _handle_idle_new_policy(client, message, case, extractor, analyzer, result):
    """User describes their policy in text (no photo)."""
    message.reply(
        "I'd like to analyze your policy. Could you either:\n"
        "1. Send a photo of the policy document (the first page with details), or\n"
        "2. Tell me: policy name, annual premium, term, and sum assured\n\n"
        "A photo is better — I can read the charges and surrender table from it."
    )


def _handle_idle_question(client, message, case, extractor, analyzer, result):
    """User asks an insurance question before sharing a policy."""
    message.reply(WELCOME_MESSAGE)


def _handle_policy_received_info(client, message, case, extractor, analyzer, result):
    """User provides additional info after sending the policy photo."""
    info = result.get("extracted_info", {})

    # Try to extract age from the message
    text = message.text.strip()
    if text.isdigit():
        age = int(text)
        if 18 <= age <= 80:
            case_manager.update_case(case.case_id, user_age=age)
            message.typing()
            _run_analysis(client, message, case, analyzer)
            return

    # Check for other extracted info
    if info.get("user_age"):
        case_manager.update_case(case.case_id, user_age=int(info["user_age"]))
        message.typing()
        _run_analysis(client, message, case, analyzer)
        return

    # If they typed policy details manually
    if info.get("policy_name") or info.get("annual_premium"):
        updated_data = {**case.policy_data}
        for key in ["policy_name", "annual_premium", "policy_term_years", "sum_assured", "insurer"]:
            if info.get(key):
                updated_data[key] = info[key]
        case_manager.update_case(case.case_id, policy_data=updated_data)

        missing = PolicyExtractor(None).validate_extraction(updated_data)
        if not missing:
            message.reply("Got all the details. How old are you? (For the term plan comparison.)")
        else:
            message.reply(f"Thanks. I still need: {', '.join(missing)}.")
        return

    message.reply("I need your age to run the comparison. Just type the number (e.g., 32).")


def _handle_analyzed_confirm(client, message, case, extractor, analyzer, result):
    """User confirms they want the letter drafted."""
    analysis = case.analysis_result
    calc = case.calculation_results
    data = case.policy_data

    message.typing()

    if analysis.get("recommended_action") == "free_look_cancel":
        letter = analyzer.draft_free_look_letter(
            policy_name=data.get("policy_name", "Unknown"),
            insurer=data.get("insurer", "Unknown"),
            policy_number="[Your policy number]",
            purchase_date=data.get("policy_start_date", "Unknown"),
            annual_premium=float(data.get("annual_premium", 0)),
            free_look_days=calc.get("free_look_days", 15),
        )
        case_manager.advance_state(case.case_id, CaseState.FREE_LOOK)
        case_manager.advance_state(case.case_id, CaseState.CANCELLATION_DRAFTED)
    else:
        letter = analyzer.draft_complaint_letter(
            policy_name=data.get("policy_name", "Unknown"),
            insurer=data.get("insurer", "Unknown"),
            annual_premium=float(data.get("annual_premium", 0)),
            policy_type=data.get("policy_type", "unknown"),
            purchase_date=data.get("policy_start_date", "Unknown"),
            xirr=calc.get("xirr", 0),
            misselling_reasons=analysis.get("misselling_reasons", []),
        )
        case_manager.advance_state(case.case_id, CaseState.COMPLAINT)

    # Build Gmail link
    subject = f"Insurance Policy Complaint — {data.get('policy_name', 'Policy')}"
    gmail_link = build_gmail_compose_url(
        to="[insurer grievance email]",
        subject=subject,
        body=letter,
    )

    message.reply(
        f"Here's your letter:\n\n---\n\n{letter}\n\n---\n\n"
        f"To send it from your own email, tap this link:\n{gmail_link}\n\n"
        f"Reply CONFIRM once you've sent it."
    )
    case_manager.complete_action(case.case_id, "Draft complaint letter", "Letter drafted")


def _handle_complaint_confirm(client, message, case, extractor, analyzer, result):
    """User confirms they sent the complaint letter."""
    case_manager.advance_state(case.case_id, CaseState.COMPLAINT_SENT)
    case_manager.add_action(
        case.case_id,
        "Wait for insurer response (15 days)",
        _now_iso(),
    )
    message.reply(
        "Your complaint is sent. The insurer has 15 days to respond.\n\n"
        "If they don't respond or reject it, I'll draft an escalation "
        "to Bima Bharosa (IRDAI's complaint portal).\n\n"
        "I'll check back with you. Type STATUS anytime for an update."
    )


def _handle_status(client, message, case, extractor, analyzer, result):
    """User asks for a status update."""
    timeline = case_manager.get_timeline(case.case_id)
    message.reply(timeline)


def _handle_unknown(client, message, case, extractor, analyzer, result):
    """Fallback for unrecognized intents."""
    if case.state == CaseState.IDLE:
        message.reply(WELCOME_MESSAGE)
    else:
        message.reply(
            "I can help with your insurance policy. You can:\n"
            "- Send a photo of a new policy to analyze\n"
            "- Type STATUS for your case update\n"
            "- Ask a question about insurance terms\n\n"
            "What would you like to do?"
        )


_STATE_ROUTER: dict = {
    CaseState.IDLE: {
        "NEW_POLICY": _handle_idle_new_policy,
        "QUESTION": _handle_idle_question,
        "STATUS_CHECK": _handle_status,
    },
    CaseState.POLICY_RECEIVED: {
        "INFO_RESPONSE": _handle_policy_received_info,
        "STATUS_CHECK": _handle_status,
    },
    CaseState.ANALYZED: {
        "CONFIRM_ACTION": _handle_analyzed_confirm,
        "STATUS_CHECK": _handle_status,
        "QUESTION": _handle_unknown,
    },
    CaseState.COMPLAINT: {
        "CONFIRM_ACTION": _handle_complaint_confirm,
        "STATUS_CHECK": _handle_status,
    },
    CaseState.COMPLAINT_SENT: {
        "STATUS_CHECK": _handle_status,
        "CONFIRM_ACTION": _handle_unknown,
    },
}
