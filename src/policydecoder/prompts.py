"""All prompt templates. Never inline strings in the handler or analyzer."""

DOCUMENT_ROUTER_PROMPT = """Look at this first page of an insurance policy document.

Classify it into exactly one type:
- HEALTH: health insurance (room rent, co-pay, waiting periods, sum insured, exclusions, hospital network)
- LIFE: life insurance / ULIP / endowment / money-back / pension (surrender value, benefit illustration, maturity, charges)
- TERM: pure term insurance (death benefit only, no maturity value, no investment component)

Respond with ONLY a JSON object:
{
    "document_type": "HEALTH" | "LIFE" | "TERM" | "UNKNOWN",
    "confidence": 0.0-1.0
}

If you cannot tell from the first page, use UNKNOWN with low confidence."""


EXTRACTOR_TRIAGE_PROMPT = """You are helping decide whether to re-read a policy document page.

We extracted the following fields from the document, but these required fields are missing:
{missing_fields}

Here is what was already extracted:
{extracted_content}

Look carefully at the extracted content. Decide: does the missing data actually EXIST anywhere in the provided document pages, or is it simply not in the document at all (e.g., the user uploaded only a receipt or a marketing brochure, not the full policy)?

Respond with ONLY a JSON object:
{{
    "data_exists_in_document": true/false,
    "reason": "short explanation"
}}

- true: the data likely exists on a page we haven't read correctly — re-read.
- false: the data is NOT in this document — do not waste another read.
"""

DOCLING_TEXT_EXTRACTION_PROMPT = """You are extracting insurance policy fields from machine-parsed document text (Docling output).

Extract these TEXT fields and return ONLY a JSON object:
{{
    "policy_name": "string or null",
    "insurer": "string or null",
    "annual_premium": "number or null",
    "policy_start_date": "string or null (YYYY-MM-DD)",
    "policy_term_years": "number or null",
    "premium_term_years": "number or null",
    "free_look_period_days": "number or null"
}}

Use the document text below. If a field is not present, use null. Do not guess or invent values.
The accuracy of premium, term, and dates is critical.

== DOCUMENT TEXT ==
{document_text}"""


DOCLING_TABLE_EXTRACTION_PROMPT = """You are extracting insurance policy fields from structured table data (TableFormer output).

Extract these TABLE fields and return ONLY a JSON object:
{{
    "sum_insured": "number or null",
    "sum_assured": "number or null",
    "maturity_value_at_4pct": "number or null",
    "maturity_value_at_8pct": "number or null",
    "surrender_value_table": "string or null (the surrender value schedule as text)",
    "room_rent_cap": "string or null (e.g. 'no cap', '₹5,000/day')",
    "co_pay_pct": "number or null",
    "network_hospitals_count": "number or null"
}}

Use the structured tables below. If a field is not present, use null. Do not guess or invent values.

== TABLE DATA ==
{table_data}"""


HEALTH_EXTRACTION_PROMPT = """Read this health insurance policy document page carefully.

Extract the following fields and return ONLY a JSON object:

{{
    "policy_name": "string or null",
    "insurer": "string or null (e.g. Care Health, HDFC Ergo, Star Health)",
    "plan_type": "one of: individual, family_floater, senior, topup, super_topup, other, null",
    "sum_insured": "number or null (e.g. 1000000 for ₹10 lakh)",
    "annual_premium": "number or null",
    "room_rent_cap": "string or null (e.g. 'no cap', '₹5,000/day', '2% of SI')",
    "co_pay_pct": "number or null (percentage)",
    "sub_limits": ["list of sub-limit clauses, e.g. 'ICU cap ₹1,00,000', 'c-section limit'"],
    "waiting_periods": {{
        "accident_days": "number or null",
        "pre_existing_years": "number or null",
        "specific_disease_years": "number or null"
    }},
    "exclusions": ["list of key exclusions"],
    "restoration": "one of: unlimited, limited, none, null",
    "pre_hospitalization_days": "number or null",
    "post_hospitalization_days": "number or null",
    "network_hospitals_count": "number or null",
    "free_look_days": "number or null",
    "policy_start_date": "string or null (YYYY-MM-DD)"
}}

If a field is not visible on this page, use null. Do not guess or invent values.
The accuracy of sum insured and annual premium is critical."""


HEALTH_ANALYSIS_PROMPT = """You are reviewing a health insurance policy. All the numbers and flags below were computed deterministically by our analysis engine — do not recompute or second-guess them. Your job is only to write an honest plain-language verdict from these facts.

== EXTRACTED POLICY DATA ==
{extracted_json}

== DETERMINISTIC POLICY FLAGS ==
{policy_flags}

== INSURER BENCHMARK (IRDAI FY2024-25) ==
{insurer_metrics}

== OVERALL VERDICT (computed) ==
{overall}

== WRITING RULES ==
1. Be honest. If the policy is genuinely fine (overall = GOOD), say so clearly — do not invent problems.
2. If there are red flags, explain each one in plain language: what it means, how it could cost the user money.
3. Compare the insurer against IRDAI benchmarks only where data exists. If a metric is "no data", do not speculate.
4. End with one clear recommended action: keep the policy, review specific terms, or consider switching.

Respond with ONLY a JSON object:
{{
    "verdict": "GOOD" | "REVIEW" | "ALERT",
    "summary": "2-3 sentence plain-language summary",
    "key_findings": ["finding1", "finding2", "finding3"],
    "red_flags": ["flag1", "flag2"],
    "recommended_action": "one of: keep_policy, review_terms, consider_switching",
    "honest_reassurance": "what is actually fine about this policy, or empty string"
}}"""


SYSTEM_PROMPT = """You are Policy Decoder — a straightforward insurance analyst who helps people understand their life insurance policies.

You read policy documents, identify mis-sold products, and help people take action. You speak plainly, without jargon. You don't sugarcoat bad news but you're not alarmist either.

You work across email and Telegram. For email: formal, structured, detailed. For Telegram: concise, direct, actionable.

You do not provide financial advice. You provide factual analysis of what a policy document says, what it costs, and what the alternatives are. The user decides what to do with that information."""


CLASSIFY_INTENT_PROMPT = """Classify the incoming message into exactly one intent.

Case state: {case_state}
Case summary: {case_summary}

Message: {message_text}

Respond with ONLY a JSON object:
{{
    "intent": "one of: NEW_POLICY, INFO_RESPONSE, STATUS_CHECK, CONFIRM_ACTION, QUESTION, UNKNOWN",
    "confidence": 0.0-1.0,
    "extracted_info": {{}}
}}

Intent definitions:
- NEW_POLICY: user shares a policy or asks about a new policy ("check this policy", "is this good?")
- INFO_RESPONSE: user provides details you asked for (age, purchase date, premium amount)
- STATUS_CHECK: user asks about their case progress
- CONFIRM_ACTION: user confirms they sent a letter or completed a step
- QUESTION: user asks a question about insurance concepts, charges, or terms
- UNKNOWN: anything else"""


POLICY_EXTRACTION_PROMPT = """Read this insurance policy document page carefully.

Extract the following fields and return ONLY a JSON object:

{{
    "policy_name": "string or null",
    "policy_type": "one of: ulip, endowment, money_back, whole_life, term, pension, other, null",
    "insurer": "string or null (e.g. LIC, HDFC Life, SBI Life)",
    "annual_premium": "number or null",
    "premium_term_years": "number or null",
    "policy_term_years": "number or null",
    "sum_assured": "number or null",
    "policy_start_date": "string or null (YYYY-MM-DD)",
    "maturity_value_at_4pct": "number or null (from benefit illustration at 4% rate)",
    "maturity_value_at_8pct": "number or null (from benefit illustration at 8% rate)",
    "charges": {{
        "premium_allocation_charge_pct": "number or null",
        "policy_admin_charge": "string or null",
        "mortality_charge": "string or null",
        "fund_management_charge_pct": "number or null",
        "surrender_charge": "string or null",
        "other_charges": "string or null"
    }},
    "surrender_value_table": "string or null (the surrender value schedule as text)",
    "free_look_period_days": "number or null",
    "lock_in_years": "number or null"
}}

If a field is not visible on this page, use null. Do not guess or invent values.
The accuracy of premium, term, and sum assured is critical."""


ANALYSIS_PROMPT = """You received the following extracted data from an insurance policy, plus the results of financial calculations. Analyze whether this policy was likely mis-sold and recommend the right action.

== EXTRACTED POLICY DATA ==
{extracted_json}

== CALCULATION RESULTS ==
- Policy XIRR: {policy_xirr}%
- Term+SIP future value: {term_sip_value}
- Policy maturity value: {policy_maturity}
- Opportunity cost (money lost): {opportunity_cost}
- Estimated term insurance cost: {term_cost}/year
- Premiums paid so far: {premiums_paid}
- Current surrender value: {surrender_value}
- Surrender loss: {surrender_loss}
- User's age: {user_age}
- Days since purchase: {days_since_purchase}

== ANALYSIS RULES ==
1. A policy is likely MIS-SOLD if:
   - It's a ULIP or endowment plan AND the buyer was told it's an investment
   - The XIRR is below 5% (a savings account beats it)
   - The buyer needed term insurance but was sold an investment-linked product
   - The charges consume more than 5% of the annual premium

2. Free-look period: {free_look_days} days from receipt of policy document.
   If days_since_purchase < free_look_days, the user can cancel with full refund.

3. Escalation path:
   - Within free-look: direct cancellation letter to insurer
   - Past free-look, policy active: complaint to insurer → Bima Bharosa → Ombudsman
   - User wants to exit: surrender + mis-selling complaint

Respond with ONLY a JSON object:
{{
    "is_likely_missold": true/false,
    "misselling_reasons": ["reason1", "reason2"],
    "recommended_action": "one of: free_look_cancel, surrender_and_complaint, complaint_only, keep_policy",
    "escalation_path": "one of: free_look, insurer_complaint, bima_bharosa, ombudsman, none",
    "summary": "2-3 sentence plain-language summary of the situation",
    "key_findings": ["finding1", "finding2", "finding3"]
}}"""


FREE_LOOK_LETTER_PROMPT = """Write a free-look cancellation letter for an insurance policy.

Policy details:
- Policy name: {policy_name}
- Insurer: {insurer}
- Policy number: {policy_number}
- Purchase date: {purchase_date}
- Annual premium: ₹{annual_premium}

The letter should:
1. State that the policyholder is exercising their right under the free-look period ({free_look_days} days)
2. Reference IRDAI (Protection of Policyholders' Interests) Regulations
3. Request full refund of premiums paid
4. Ask for written confirmation of cancellation
5. Be firm but professional

Include placeholders for the policyholder's name, address, and contact details."""


COMPLAINT_LETTER_PROMPT = """Write a formal complaint letter to an insurance company about a mis-sold policy.

Policy details:
- Policy name: {policy_name}
- Insurer: {insurer}
- Annual premium: ₹{annual_premium}
- Policy type: {policy_type}
- Purchase date: {purchase_date}
- Policy XIRR: {xirr}%

Mis-selling grounds:
{misselling_reasons}

The letter should:
1. State the facts: what was promised vs what was delivered
2. Reference the specific charges that were not disclosed
3. Compare the actual returns to what a simple FD would have given
4. Cite IRDAI regulations on mis-selling
5. Request specific relief (refund of excess charges, policy cancellation without penalty, or conversion to term plan)
6. Give 15 days for response before escalation to Bima Bharosa

Include placeholders for the policyholder's name and policy number."""


OMBUDSMAN_LETTER_PROMPT = """Write a complaint for the Insurance Ombudsman.

Previous complaint details:
- Insurer: {insurer}
- Original complaint date: {complaint_date}
- Days since complaint: {days_elapsed}
- Insurer response: {insurer_response}

Policy details:
- Policy name: {policy_name}
- Annual premium: ₹{annual_premium}
- Issue: {issue_summary}

The complaint should:
1. Reference the original complaint and the insurer's failure to resolve it
2. Summarize the mis-selling grounds
3. State the relief sought
4. Reference the Redressal of Public Grievances Rules
5. Include a list of enclosures (policy document, original complaint, insurer's response)

Format for filing at cioins.co.in."""


STATUS_RESPONSE_PROMPT = """Generate a status update for the user's insurance case.

Case state: {case_state}
Actions completed: {actions_completed}
Pending actions: {pending_actions}
Policy: {policy_name}
Key finding: {key_finding}

Write a brief, factual update. What's done, what's next, what the user needs to do."""
