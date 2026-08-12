"""Extractor Agent — reads a policy document with short-circuit + Docling routing.

Single responsibility: turn media (PDF pages / photos) into a validated
extraction dict.

Routing (Gap 1 + Gap 3):
- PDF + Docling enabled → Docling parse → text LLM over markdown chunks,
  table LLM over tables JSON, vision only as single-page fallback.
- Photos (.jpg/.png) → vision-only path (no Docling).
- Short-circuit: if the doc genuinely lacks required data, triage returns
  {"data_exists_in_document": false} and we exit early. Hard cap: 1 retry.
"""

import json
from pathlib import Path
from typing import Any

from policydecoder.agents.base import BaseAgent
from policydecoder.config import get_config
from policydecoder.docling_parser import parse_document
from policydecoder.extractor import PolicyExtractor, parse_json_response
from policydecoder.prompts import (
    DOCLING_TABLE_EXTRACTION_PROMPT,
    DOCLING_TEXT_EXTRACTION_PROMPT,
    EXTRACTOR_TRIAGE_PROMPT,
)

# Hard cap on re-reads after the initial pass.
MAX_RETRIES = 1

# Per-document-type required fields (mirrors the schemas).
_REQUIRED = {
    "HEALTH": ["sum_insured", "annual_premium"],
    "LIFE": ["policy_name", "annual_premium", "policy_term_years", "sum_assured"],
}

_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


class ExtractorAgent(BaseAgent):
    """Agentic extraction with short-circuit + Docling routing."""

    def __init__(self, extractor: PolicyExtractor, llm_client, model: str | None = None):
        super().__init__(llm_client, model)
        self.extractor = extractor
        self.docling_enabled = get_config().docling_enabled
        self.docling_text_model = get_config().docling_text_model

    async def run(  # type: ignore[override]
        self,
        media_urls: list[str],
        document_type: str = "HEALTH",
        input_path: str | None = None,
    ) -> dict[str, Any]:
        """Extract with validation + short-circuit. Returns
        {data, missing, short_circuited}."""

        # Route: local PDF → Docling; photos → vision; no input → nothing.
        if input_path and self._is_pdf(input_path) and self.docling_enabled:
            data = self._extract_with_docling(input_path, document_type)
        elif media_urls:
            data = self._extract_vision(media_urls, document_type)
        elif input_path:
            # Local PDF but Docling disabled → vision path (no URLs yet).
            data = self._extract_vision([], document_type)
        else:
            data = {}

        missing = self._missing(data, document_type)
        if not missing:
            return {"data": data, "missing": [], "short_circuited": False}

        # Triage: does the missing data exist in this document at all?
        exists = self._triage(missing, data)
        if not exists:
            return {"data": data, "missing": missing, "short_circuited": True}

        # One targeted re-read, then give up.
        if input_path and self._is_pdf(input_path) and self.docling_enabled:
            retried = self._vision_fallback(input_path, document_type, missing_fields=missing)
        else:
            retried = self._extract_vision(media_urls, document_type)
        for key, value in retried.items():
            if value is not None and not data.get(key):
                data[key] = value
        missing_after = self._missing(data, document_type)
        return {
            "data": data,
            "missing": missing_after,
            "short_circuited": False,
        }

    # ------------------------------------------------------------------
    # Routing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_pdf(input_path: str) -> bool:
        return Path(input_path).suffix.lower() == ".pdf"

    def _extract_vision(self, media_urls: list[str], document_type: str) -> dict[str, Any]:
        extract_fn = (
            self.extractor.extract_health
            if document_type == "HEALTH"
            else self.extractor.extract_life
        )
        return extract_fn(media_urls)

    def _extract_with_docling(self, input_path: str, document_type: str) -> dict[str, Any]:
        """Docling path: text LLM over markdown + table LLM over tables JSON."""
        result = parse_document(Path(input_path))
        if result is None:
            return self._extract_vision([], document_type)

        text_fields = self._extract_text_fields(result["markdown"])
        table_fields = self._extract_table_fields(result["tables_json"])

        data = {**table_fields, **text_fields}
        return data

    def _extract_text_fields(self, markdown: str) -> dict[str, Any]:
        """Text-LLM extraction over markdown.

        The schedule + benefit illustration + premium tables often live in the
        middle of these welcome-letter documents (e.g. Policybazaar letters put
        the premium table ~17k chars in). Scan head + middle + tail windows
        rather than one contiguous blob, so key fields are never omitted.
        """
        head = markdown[:8000]
        middle = ""
        tail = markdown[-8000:] if len(markdown) > 16000 else ""

        if len(markdown) > 24000:
            mid_start = len(markdown) // 2 - 4000
            middle = markdown[mid_start : mid_start + 8000]
            combined = (
                f"{head}\n[...middle 1 omitted...]\n{middle}\n[...middle 2 omitted...]\n{tail}"
            )
        elif len(markdown) > 16000:
            combined = f"{head}\n[...middle omitted...]\n{tail}"
        else:
            combined = head

        prompt = DOCLING_TEXT_EXTRACTION_PROMPT.format(document_text=combined)
        content = self.generate("You are a policy text extractor.", prompt, timeout=20)
        parsed = parse_json_response(content)
        return parsed if parsed else {}

    def _extract_table_fields(self, tables_json: list[Any]) -> dict[str, Any]:
        prompt = DOCLING_TABLE_EXTRACTION_PROMPT.format(
            table_data=json.dumps(tables_json, ensure_ascii=False)[:12000]
        )
        content = self.generate("You are a policy table extractor.", prompt, timeout=20)
        parsed = parse_json_response(content)
        return parsed if parsed else {}

    def _vision_fallback(
        self, input_path: str, document_type: str, missing_fields: list[str]
    ) -> dict[str, Any]:
        """Vision fallback: render a PDF page to an image and read it.

        The Docling + text/table LLM missed some fields; triage confirmed
        they exist in a page image. Render the relevant page(s) and run
        the vision model on the image.
        """
        from policydecoder.docling_parser import render_page

        out_dir = Path(input_path).parent / ".rendered_pages"
        data: dict[str, Any] = {}
        # Check a few key pages (1, 2, 3) for the missing fields.
        for page_no in (1, 2, 3):
            image_path = render_page(Path(input_path), page_no, out_dir)
            if image_path is None:
                continue
            result = self.extractor.extract_from_image_path(str(image_path))
            for key, value in result.items():
                if value is not None and not data.get(key):
                    data[key] = value
            if not self._missing(data, document_type):
                break
        return data

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
            return False
        return bool(parsed.get("data_exists_in_document", False))
