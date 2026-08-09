"""Supervisor — async orchestrator of the specialist agents.

Single responsibility: receive a message, route it, fan out independent
agents in parallel (Extractor + Researcher via asyncio.gather), then
run the dependent analyst + drafter sequentially.

Sets the correlation ID and starts the per-message Opik trace so all
agent spans nest under one trace.
"""

import asyncio
from typing import Any

from policydecoder.agents.health_analyst import HealthAnalyst
from policydecoder.agents.life_analyst import LifeAnalyst
from policydecoder.agents.researcher_agent import ResearcherAgent
from policydecoder.logging import get_logger, set_correlation_id
from policydecoder.opik_tracing import start_trace


class Supervisor:
    """Orchestrates router → gather(extractor, researcher) → analyst → drafter."""

    def __init__(
        self,
        router,
        extractor,
        researcher: ResearcherAgent,
        health_analyst: HealthAnalyst,
        life_analyst: LifeAnalyst,
        letter_drafter,
    ):
        self.router = router
        self.extractor = extractor
        self.researcher = researcher
        self.health_analyst = health_analyst
        self.life_analyst = life_analyst
        self.letter_drafter = letter_drafter
        self.logger = get_logger("policydecoder.supervisor")

    async def process_media(
        self,
        media_urls: list[str],
        conversation_id: str = "",
        channel: str = "unknown",
    ) -> dict[str, Any]:
        set_correlation_id(conversation_id)
        start_trace(conversation_id, channel)

        # Router decides the document type.
        label, confidence = await self._classify(media_urls)
        document_type = label if label in ("HEALTH", "LIFE") else "LIFE"

        # Fan out independent agents in parallel.
        extract_task = self.extractor.run(media_urls=media_urls, document_type=document_type)
        research_task = self.researcher.run(topic=self._research_topic(document_type))
        extraction, findings = await asyncio.gather(extract_task, research_task)

        if extraction.get("short_circuited"):
            return {
                "reply": "I need the full policy document — you only uploaded a partial document. "
                "Please share the complete policy pages.",
                "missing": extraction["missing"],
            }

        data = extraction.get("data", {})
        if document_type == "HEALTH":
            analysis = await self.health_analyst.run(extraction=data, findings=findings)
        else:
            calc = self._life_calc(data)
            analysis = await self.life_analyst.run(
                extraction=data, calc_results=calc, findings=findings
            )
            analysis["_calc_results"] = calc

        return {"data": data, "analysis": analysis, "findings": findings}

    async def process_text(self, text: str) -> dict[str, Any]:
        """Route a text-only message (question, status, etc.)."""
        return {"reply": None, "text": text}

    async def _classify(self, media_urls: list[str]) -> tuple[str, float]:
        """Ask the router agent. Falls back to LIFE on failure."""
        if self.router is None:
            return "LIFE", 0.0
        try:
            label, confidence = await self.router.run(media_urls=media_urls)
            return label, confidence
        except Exception as e:
            self.logger.warning("Router failed, defaulting to LIFE: %s", e)
            return "LIFE", 0.0

    @staticmethod
    def _research_topic(document_type: str) -> str:
        return "how_to_choose_health" if document_type == "HEALTH" else "how_to_choose_term"

    @staticmethod
    def _life_calc(data: dict[str, Any]) -> dict[str, Any]:
        """Minimal calc wrapper — full pipeline lives in the handler for now."""
        return {"xirr": 0.0}
