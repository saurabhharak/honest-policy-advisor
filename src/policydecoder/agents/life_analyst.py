"""Life Analyst Agent — XIRR + mis-selling verdict.

Single responsibility: given validated life extraction + calc results +
optional Researcher findings, produce the mis-selling verdict. All math
is pre-computed by calculator.py; the LLM only interprets the numbers.
"""

import json
from typing import Any

from policydecoder.agents.base import BaseAgent
from policydecoder.analyzer import PolicyAnalyzer


class LifeAnalyst(BaseAgent):
    """Wraps PolicyAnalyzer.analyze_policy with pre-computed calc results."""

    def __init__(
        self, llm_client, model: str | None = None, analyzer: PolicyAnalyzer | None = None
    ):
        super().__init__(llm_client, model)
        self.analyzer = analyzer or PolicyAnalyzer(llm_client)

    async def run(  # type: ignore[override]
        self,
        extraction: dict[str, Any],
        calc_results: dict[str, Any],
        findings: list[dict[str, Any]],
        **inputs: Any,
    ) -> dict[str, Any]:
        analysis = self.analyzer.analyze_policy(
            extracted_json=json.dumps(extraction, ensure_ascii=False),
            policy_xirr=calc_results.get("xirr", 0),
            term_sip_value=calc_results.get("term_sip_value", 0),
            policy_maturity=calc_results.get("policy_maturity", 0),
            opportunity_cost=calc_results.get("opportunity_cost", 0),
            term_cost=calc_results.get("term_cost", 0),
            premiums_paid=calc_results.get("premiums_paid", 0),
            surrender_value=calc_results.get("surrender_value", 0),
            surrender_loss=calc_results.get("surrender_loss", 0),
            user_age=calc_results.get("user_age", 30),
            days_since_purchase=calc_results.get("days_since_purchase", 0),
            free_look_days=calc_results.get("free_look_days", 15),
        )
        analysis["_researcher_findings"] = findings
        return analysis
