"""Policy PDF extraction via vision model.

Sends the policy document (or key pages) to a vision model and gets back
structured JSON. The vision model reads the document; it doesn't analyze
or make recommendations — that's analyzer.py's job.

Extraction is routed per document type: health policies use
HealthPolicyExtraction, life policies use LifePolicyExtraction.
"""

import json
from typing import Any

from openai import OpenAI

from policydecoder.config import get_config
from policydecoder.logging import get_logger
from policydecoder.opik_tracing import trace_llm
from policydecoder.prompts import (
    HEALTH_EXTRACTION_PROMPT,
    POLICY_EXTRACTION_PROMPT,
)
from policydecoder.schemas import HealthPolicyExtraction, LifePolicyExtraction


def parse_json_response(text: str) -> dict[str, Any]:
    """Extract the first JSON object from an LLM response, tolerating noise."""
    if not text or not text.strip():
        return {}

    stripped = text.strip()

    # Direct parse
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Strip markdown fences
    if stripped.startswith("```"):
        fenced = stripped.strip("`").strip()
        if fenced.startswith("json"):
            fenced = fenced[4:].strip()
        try:
            return json.loads(fenced)
        except json.JSONDecodeError:
            pass

    # Handle truncated leading brace
    if not stripped.startswith("{"):
        try:
            return json.loads("{" + stripped)
        except json.JSONDecodeError:
            pass
        try:
            return json.loads('{"' + stripped)
        except json.JSONDecodeError:
            pass

    # Find the largest balanced { ... } block
    start = stripped.find("{")
    if start != -1:
        best = None
        i = start
        while i < len(stripped):
            depth = 0
            for j in range(i, len(stripped)):
                if stripped[j] == "{":
                    depth += 1
                elif stripped[j] == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = stripped[i : j + 1]
                        try:
                            parsed = json.loads(candidate)
                        except json.JSONDecodeError:
                            parsed = None
                        if parsed is not None and (
                            best is None or len(candidate) > len(json.dumps(best))
                        ):
                            best = parsed
                        break
            i = stripped.find("{", i + 1)
            if i == -1:
                break
        if best is not None:
            return best

    return {}


class PolicyExtractor:
    """Extracts structured data from insurance policy PDFs via vision model."""

    def __init__(self, llm_client: OpenAI | None):
        self.llm = llm_client
        self.vision_model = get_config().vision_model
        self.logger = get_logger("policydecoder.extractor")

    def extract_from_image(self, media_url: str) -> dict[str, Any]:
        """Extract policy details from a photo of the policy document.

        Works for both email attachments and Telegram photos — the Caspian
        SDK normalizes both into media URLs.
        """
        assert self.llm is not None, "extract_from_image requires an LLM client"
        try:
            response = self.llm.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": POLICY_EXTRACTION_PROMPT},
                            {"type": "image_url", "image_url": {"url": media_url}},
                        ],
                    }
                ],
                max_tokens=1500,
                timeout=60,
            )
            content = response.choices[0].message.content or ""
            parsed = parse_json_response(content)
            if parsed:
                trace_llm(
                    "extract_vision",
                    model=self.vision_model,
                    input_text=f"media={media_url[:80]}",
                    output_text=content[:500],
                    metadata={"media_url": media_url[:80]},
                )
                return parsed
        except Exception as e:
            self.logger.warning("Vision extraction failed for %s: %s", media_url[:60], e)
        return {}

    def extract_from_images(self, media_urls: list[str]) -> dict[str, Any]:
        """Extract from multiple pages and merge results.

        A policy PDF photo may span multiple pages. Each page shows part
        of the data. First non-null value wins per field.
        """
        merged: dict[str, Any] = {}
        for url in media_urls:
            result = self.extract_from_image(url)
            for key, value in result.items():
                if value is not None and not merged.get(key):
                    merged[key] = value
        return merged

    def extract_health(self, media_urls: list[str]) -> dict[str, Any]:
        """Extract health policy fields using the health schema."""
        raw = self._extract_pages(media_urls, HEALTH_EXTRACTION_PROMPT)
        try:
            return HealthPolicyExtraction.model_validate(raw).model_dump()
        except Exception as e:
            print(f"[EXTRACTOR] Health schema validation failed: {e}")
            return raw

    def extract_life(self, media_urls: list[str]) -> dict[str, Any]:
        """Extract life policy fields using the life schema."""
        raw = self._extract_pages(media_urls, POLICY_EXTRACTION_PROMPT)
        try:
            return LifePolicyExtraction.model_validate(raw).model_dump()
        except Exception as e:
            print(f"[EXTRACTOR] Life schema validation failed: {e}")
            return raw

    def _extract_pages(self, media_urls: list[str], prompt: str) -> dict[str, Any]:
        """Run the vision model over each page and merge results."""
        if not media_urls:
            return {}
        if len(media_urls) == 1:
            return self._extract_single(media_urls[0], prompt)
        merged: dict[str, Any] = {}
        for url in media_urls:
            result = self._extract_single(url, prompt)
            for key, value in result.items():
                if value is not None and not merged.get(key):
                    merged[key] = value
        return merged

    def _extract_single(self, media_url: str, prompt: str) -> dict[str, Any]:
        """Call the vision model once for a single page."""
        assert self.llm is not None, "_extract_single requires an LLM client"
        try:
            response = self.llm.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": media_url}},
                        ],
                    }
                ],
                max_tokens=1500,
                timeout=60,
            )
            content = response.choices[0].message.content or ""
            parsed = parse_json_response(content)
            if parsed:
                trace_llm(
                    "extract_vision_page",
                    model=self.vision_model,
                    input_text=f"media={media_url[:80]}",
                    output_text=content[:500],
                    metadata={"media_url": media_url[:80]},
                )
                return parsed
        except Exception as e:
            self.logger.warning("Vision extraction failed for %s: %s", media_url[:60], e)
        return {}

    def validate_extraction(self, data: dict[str, Any]) -> list[str]:
        """Check if the extracted data has the minimum required fields.

        Returns a list of missing field names. Empty list = extraction is usable.
        """
        required = [
            "policy_name",
            "annual_premium",
            "policy_term_years",
            "sum_assured",
        ]
        missing = []
        for field_name in required:
            if not data.get(field_name):
                missing.append(field_name)
        return missing
