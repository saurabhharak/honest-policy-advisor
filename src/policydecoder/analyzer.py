"""LLM-driven analysis and letter drafting.

The LLM receives extracted data and calculation results, then decides:
1. Was this policy mis-sold?
2. What's the right escalation path?
3. Draft the appropriate letter.

The LLM never does math. It receives numbers from calculator.py.
"""

from typing import Any

from openai import OpenAI

from policydecoder.config import get_config
from policydecoder.extractor import parse_json_response, response_text
from policydecoder.guardrails import validate_letter_output
from policydecoder.logging import get_logger
from policydecoder.opik_tracing import trace_llm
from policydecoder.prompts import (
    ANALYSIS_PROMPT,
    CLASSIFY_INTENT_PROMPT,
    COMPLAINT_LETTER_PROMPT,
    FREE_LOOK_LETTER_PROMPT,
    HEALTH_ANALYSIS_PROMPT,
    OMBUDSMAN_LETTER_PROMPT,
    STATUS_RESPONSE_PROMPT,
    SYSTEM_PROMPT,
)


class PolicyAnalyzer:
    """Analyzes policies and drafts letters via LLM."""

    def __init__(self, llm_client: OpenAI):
        self.llm = llm_client
        self.model = get_config().llm_model
        self.logger = get_logger("policydecoder.analyzer")

    def _generate(self, system: str, user: str, timeout: float = 15.0) -> str:
        try:
            response = self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.7,
                max_tokens=2000,
                timeout=timeout,
            )
            content = response_text(response)
            result = content.strip() if content else ""
            trace_llm(
                "analyzer_generate",
                model=self.model,
                input_text=user[:500],
                output_text=result[:500],
                metadata={"timeout": timeout},
            )
            return result
        except Exception as e:
            self.logger.warning("LLM call failed: %s", e)
            return ""

    def _generate_letter(self, system: str, prompt: str) -> str:
        """Generate a natural-language letter and run the output rail.

        Letters are user-facing text, so they get the disclaimer/overpromise
        sanitization rail. JSON-returning calls use _generate() directly —
        their shape is enforced by Pydantic, not NeMo.
        """
        letter = self._generate(system, prompt)
        return validate_letter_output(letter)

    def classify_intent(
        self, message_text: str, case_state: str, case_summary: str
    ) -> dict[str, Any]:
        prompt = CLASSIFY_INTENT_PROMPT.format(
            case_state=case_state,
            case_summary=case_summary,
            message_text=message_text,
        )
        result = self._generate(SYSTEM_PROMPT, prompt, timeout=10.0)
        parsed = parse_json_response(result)
        if parsed and "intent" in parsed:
            return parsed
        return {"intent": "UNKNOWN", "confidence": 0.0, "extracted_info": {}}

    def analyze_policy(
        self,
        *,
        extracted_json: str,
        policy_xirr: float,
        term_sip_value: float,
        policy_maturity: float,
        opportunity_cost: float,
        term_cost: float,
        premiums_paid: float,
        surrender_value: float,
        surrender_loss: float,
        user_age: int,
        days_since_purchase: int,
        free_look_days: int,
    ) -> dict[str, Any]:
        """Analyze a policy for mis-selling indicators.

        All numbers come from calculator.py. The LLM only interprets them.
        """
        prompt = ANALYSIS_PROMPT.format(
            extracted_json=extracted_json,
            policy_xirr=round(policy_xirr * 100, 2),
            term_sip_value=term_sip_value,
            policy_maturity=policy_maturity,
            opportunity_cost=opportunity_cost,
            term_cost=term_cost,
            premiums_paid=premiums_paid,
            surrender_value=surrender_value,
            surrender_loss=surrender_loss,
            user_age=user_age,
            days_since_purchase=days_since_purchase,
            free_look_days=free_look_days,
        )
        result = self._generate(SYSTEM_PROMPT, prompt, timeout=20.0)
        parsed = parse_json_response(result)
        if parsed and "is_likely_missold" in parsed:
            return parsed
        return {
            "is_likely_missold": None,
            "misselling_reasons": [],
            "recommended_action": "unknown",
            "escalation_path": "none",
            "summary": "Analysis could not be completed. Please try again.",
            "key_findings": [],
        }

    def analyze_health_policy(
        self,
        *,
        extracted_json: str,
        policy_flags: str,
        insurer_metrics: str,
        overall: str,
        research_findings: str = "",
    ) -> dict[str, Any]:
        """Analyze a health policy from pre-computed flags and benchmarks.

        All numbers and flags come from health_calculator.py. The LLM only
        writes the honest narrative verdict. research_findings (optional)
        are whitelisted Researcher sources appended to the prompt.
        """
        prompt = HEALTH_ANALYSIS_PROMPT.format(
            extracted_json=extracted_json,
            policy_flags=policy_flags,
            insurer_metrics=insurer_metrics,
            overall=overall,
        )
        if research_findings:
            prompt += "\n\n== RESEARCH FINDINGS (whitelisted sources) ==\n" + research_findings
        result = self._generate(SYSTEM_PROMPT, prompt, timeout=20.0)
        parsed = parse_json_response(result)
        if parsed and "verdict" in parsed:
            return parsed
        return {
            "verdict": overall,
            "summary": "Analysis could not be completed. Please try again.",
            "key_findings": [],
            "red_flags": [],
            "recommended_action": "unknown",
            "honest_reassurance": "",
        }

    def draft_free_look_letter(
        self,
        *,
        policy_name: str,
        insurer: str,
        policy_number: str,
        purchase_date: str,
        annual_premium: float,
        free_look_days: int,
    ) -> str:
        prompt = FREE_LOOK_LETTER_PROMPT.format(
            policy_name=policy_name,
            insurer=insurer,
            policy_number=policy_number,
            purchase_date=purchase_date,
            annual_premium=annual_premium,
            free_look_days=free_look_days,
        )
        return self._generate_letter(SYSTEM_PROMPT, prompt)

    def draft_complaint_letter(
        self,
        *,
        policy_name: str,
        insurer: str,
        annual_premium: float,
        policy_type: str,
        purchase_date: str,
        xirr: float,
        misselling_reasons: list[str],
    ) -> str:
        prompt = COMPLAINT_LETTER_PROMPT.format(
            policy_name=policy_name,
            insurer=insurer,
            annual_premium=annual_premium,
            policy_type=policy_type,
            purchase_date=purchase_date,
            xirr=round(xirr * 100, 2),
            misselling_reasons="\n".join(f"- {r}" for r in misselling_reasons),
        )
        return self._generate_letter(SYSTEM_PROMPT, prompt)

    def draft_ombudsman_letter(
        self,
        *,
        insurer: str,
        complaint_date: str,
        days_elapsed: int,
        insurer_response: str,
        policy_name: str,
        annual_premium: float,
        issue_summary: str,
    ) -> str:
        prompt = OMBUDSMAN_LETTER_PROMPT.format(
            insurer=insurer,
            complaint_date=complaint_date,
            days_elapsed=days_elapsed,
            insurer_response=insurer_response,
            policy_name=policy_name,
            annual_premium=annual_premium,
            issue_summary=issue_summary,
        )
        return self._generate_letter(SYSTEM_PROMPT, prompt)

    def draft_status_response(
        self,
        *,
        case_state: str,
        actions_completed: str,
        pending_actions: str,
        policy_name: str,
        key_finding: str,
    ) -> str:
        prompt = STATUS_RESPONSE_PROMPT.format(
            case_state=case_state,
            actions_completed=actions_completed,
            pending_actions=pending_actions,
            policy_name=policy_name,
            key_finding=key_finding,
        )
        return self._generate_letter(SYSTEM_PROMPT, prompt)
