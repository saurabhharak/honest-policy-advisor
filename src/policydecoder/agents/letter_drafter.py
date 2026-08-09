"""Letter Drafter Agent — writes the complaint/cancellation letters.

Single responsibility: given the verdict + case data, produce the
appropriate letter (free-look cancellation, insurer complaint, or
ombudsman escalation). Output goes through the letter output rail.
"""

from typing import Any

from policydecoder.agents.base import BaseAgent
from policydecoder.analyzer import PolicyAnalyzer


class LetterDrafter(BaseAgent):
    """Wraps PolicyAnalyzer's letter-draft methods."""

    def __init__(
        self, llm_client, model: str | None = None, analyzer: PolicyAnalyzer | None = None
    ):
        super().__init__(llm_client, model)
        self.analyzer = analyzer or PolicyAnalyzer(llm_client)

    async def run(  # type: ignore[override]
        self,
        letter_type: str,
        policy_data: dict[str, Any],
        analysis: dict[str, Any],
        **inputs: Any,
    ) -> str:
        if letter_type == "free_look":
            return self.analyzer.draft_free_look_letter(
                policy_name=policy_data.get("policy_name", "Unknown"),
                insurer=policy_data.get("insurer", "Unknown"),
                policy_number="[Your policy number]",
                purchase_date=policy_data.get("policy_start_date", "Unknown"),
                annual_premium=float(policy_data.get("annual_premium", 0)),
                free_look_days=int(policy_data.get("free_look_period_days") or 15),
            )
        if letter_type == "ombudsman":
            return self.analyzer.draft_ombudsman_letter(
                insurer=policy_data.get("insurer", "Unknown"),
                complaint_date="[date of your complaint]",
                days_elapsed=15,
                insurer_response="No response received",
                policy_name=policy_data.get("policy_name", "Unknown"),
                annual_premium=float(policy_data.get("annual_premium", 0)),
                issue_summary=analysis.get("summary", ""),
            )
        # Default: insurer complaint
        return self.analyzer.draft_complaint_letter(
            policy_name=policy_data.get("policy_name", "Unknown"),
            insurer=policy_data.get("insurer", "Unknown"),
            annual_premium=float(policy_data.get("annual_premium", 0)),
            policy_type=policy_data.get("policy_type", "unknown"),
            purchase_date=policy_data.get("policy_start_date", "Unknown"),
            xirr=float((analysis.get("_calc_results") or {}).get("xirr", 0)),
            misselling_reasons=analysis.get("misselling_reasons", []),
        )
