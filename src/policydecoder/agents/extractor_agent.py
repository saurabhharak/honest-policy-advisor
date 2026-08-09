"""Extractor Agent — reads a policy document with a short-circuit retry loop.

Single responsibility: turn media (PDF pages / photos) into a validated
extraction dict.

Resilience: if the document genuinely lacks the required data (e.g., the
user uploaded a receipt, not the full policy), a triage LLM check returns
{"data_exists_in_document": false} and the agent short-circuits — it never
burns retries confirming data isn't there. Hard cap: 1 retry.
"""

import json
from typing import Any

from policydecoder.agents.base import BaseAgent
from policydecoder.extractor import PolicyExtractor, parse_json_response
from policydecoder.prompts import EXTRACTOR_TRIAGE_PROMPT

# Hard cap on re-reads after the initial pass.
MAX_RETRIES = 1

# Per-document-type required fields (mirrors the schemas).
_REQUIRED = {
    "HEALTH": ["sum_insured", "annual_premium"],
    "LIFE": ["policy_name", "annual_premium", "policy_term_years", "sum_assured"],
}


class ExtractorAgent(BaseAgent):
    """Agentic extraction with short-circuit on genuinely-missing data."""

    def __init__(self, extractor: PolicyExtractor, llm_client, model: str | None = None):
        super().__init__(llm_client, model)
        self.extractor = extractor

    async def run(  # type: ignore[override]
        self, media_urls: list[str], document_type: str = "HEALTH"
    ) -> dict[str, Any]:
        """Extract with validation + short-circuit. Returns
        {data, missing, short_circuited}."""
        extract_fn = (
            self.extractor.extract_health
            if document_type == "HEALTH"
            else self.extractor.extract_life
        )

        data = extract_fn(media_urls)
        missing = self._missing(data, document_type)
        if not missing:
            return {"data": data, "missing": [], "short_circuited": False}

        # Triage: does the missing data exist in this document at all?
        exists = self._triage(missing, data)
        if not exists:
            return {"data": data, "missing": missing, "short_circuited": True}

        # One targeted re-read, then give up.
        retried = extract_fn(media_urls)
        for key, value in retried.items():
            if value is not None and not data.get(key):
                data[key] = value
        missing_after = self._missing(data, document_type)
        return {
            "data": data,
            "missing": missing_after,
            "short_circuited": False,
        }

    def _missing(self, data: dict[str, Any], document_type: str) -> list[str]:
        required = _REQUIRED.get(document_type, _REQUIRED["LIFE"])
        return [f for f in required if not data.get(f)]

    def _triage(self, missing: list[str], data: dict[str, Any]) -> bool:
        """Ask the LLM whether the missing data exists in the document."""
        prompt = EXTRACTOR_TRIAGE_PROMPT.format(
            missing_fields=", ".join(missing),
            extracted_content=json.dumps(data, ensure_ascii=False)[:1500],
        )
        content = self.generate("You are a document triage assistant.", prompt)
        parsed = parse_json_response(content)
        if parsed is None:
            # If triage is unparseable, default to false (don't waste a retry).
            return False
        return bool(parsed.get("data_exists_in_document", False))
