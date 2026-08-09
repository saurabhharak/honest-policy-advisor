"""Health Analyst Agent — scores a health policy and writes the honest verdict.

Single responsibility: given validated health extraction + optional
Researcher findings, produce the honest verdict. All math is delegated
to score_health_policy (pure function); the LLM only writes the verdict.
"""

import json
from collections.abc import Callable
from typing import Any

from policydecoder.agents.base import BaseAgent
from policydecoder.analyzer import PolicyAnalyzer
from policydecoder.health_calculator import score_health_policy


class HealthAnalyst(BaseAgent):
    """Wraps score_health_policy + PolicyAnalyzer.analyze_health_policy."""

    def __init__(
        self,
        llm_client,
        model: str | None = None,
        analyzer: PolicyAnalyzer | None = None,
        benchmark_lookup: Callable[[str], dict | None] | None = None,
    ):
        super().__init__(llm_client, model)
        self.analyzer = analyzer or PolicyAnalyzer(llm_client)
        self.benchmark_lookup = benchmark_lookup

    async def run(  # type: ignore[override]
        self, extraction: dict[str, Any], findings: list[dict[str, Any]], **inputs: Any
    ) -> dict[str, Any]:
        insurer_name = extraction.get("insurer")
        benchmark = self.benchmark_lookup(str(insurer_name)) if self.benchmark_lookup else None

        # Deterministic scoring — the LLM never does math.
        report = score_health_policy(extraction, benchmark, {})

        # Build the analysis prompt with researcher findings attached.
        findings_text = "\n".join(f"- {f['claim']} ({f['source']})" for f in findings) or ""
        analysis = self.analyzer.analyze_health_policy(
            extracted_json=json.dumps(extraction, ensure_ascii=False),
            policy_flags="\n".join(f"- {f}" for f in report["policy_flags"]) or "None",
            insurer_metrics=json.dumps(report["insurer_metrics"], ensure_ascii=False),
            overall=report["overall"],
            research_findings=findings_text,
        )
        analysis["_researcher_findings"] = findings
        return analysis
