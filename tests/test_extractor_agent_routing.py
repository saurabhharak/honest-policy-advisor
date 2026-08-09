"""Tests for the Extractor Agent's Docling routing (Gap 1 + Gap 3)."""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from policydecoder.agents.extractor_agent import ExtractorAgent

DUMMY_PDF = Path(__file__).parent / "assets" / "dummy_policy.pdf"


def _stub_docling():
    """Stub the docling module for the lazy import in docling_parser."""
    mod = types.ModuleType("docling")
    converter_mod = types.ModuleType("docling.document_converter")
    converter_mod.DocumentConverter = MagicMock()
    sys.modules["docling"] = mod
    sys.modules["docling.document_converter"] = converter_mod
    return converter_mod


def _make_agent(extraction_result, text_result=None, table_result=None, triage_result=None):
    """Build an agent with mocked vision extraction + text/table/triage LLM."""
    extractor = MagicMock()
    extractor.extract_health.return_value = extraction_result
    extractor.extract_life.return_value = extraction_result

    llm = MagicMock()
    responses = []
    if text_result is not None:
        r = MagicMock()
        r.choices[0].message.content = text_result
        responses.append(r)
    if table_result is not None:
        r = MagicMock()
        r.choices[0].message.content = table_result
        responses.append(r)
    if triage_result is not None:
        r = MagicMock()
        r.choices[0].message.content = triage_result
        responses.append(r)
    if responses:
        llm.chat.completions.create.side_effect = responses

    agent = ExtractorAgent(extractor=extractor, llm_client=llm, model="fake-model")
    return agent


def _fake_parse_result(**overrides):
    result = {
        "markdown": "# Policy\nSum Insured: 1500000\nAnnual Premium: 18000",
        "tables_json": [{"table": "data"}],
        "page_images": [],
        "page_count": 3,
        "pages_with_tables": [2],
    }
    result.update(overrides)
    return result


class TestPdfRouting:
    @pytest.mark.asyncio
    async def test_pdf_uses_docling_text_and_table(self):
        """PDF + Docling enabled: parse, text LLM over markdown, table LLM over tables."""
        agent = _make_agent(
            extraction_result={},
            text_result='{"policy_name": "Care Supreme", "annual_premium": 18000}',
            table_result='{"sum_insured": 1500000}',
        )
        with (
            patch.object(agent, "docling_enabled", True),
            patch(
                "policydecoder.agents.extractor_agent.parse_document",
                return_value=_fake_parse_result(),
            ) as mock_parse,
        ):
            result = await agent.run(
                media_urls=[], document_type="HEALTH", input_path=str(DUMMY_PDF)
            )

        mock_parse.assert_called_once()
        assert result["data"]["policy_name"] == "Care Supreme"
        assert result["data"]["sum_insured"] == 1500000
        # vision model NOT called when fields resolve via docling
        agent.extractor.extract_health.assert_not_called()

    @pytest.mark.asyncio
    async def test_photo_bypasses_docling(self):
        """Photo (.jpg) input → vision-only path, Docling not invoked (Gap 3)."""
        agent = _make_agent(
            extraction_result={
                "policy_name": "Photo Policy",
                "sum_insured": 500000,
                "annual_premium": 12000,
            },
        )
        with (
            patch.object(agent, "docling_enabled", True),
            patch("policydecoder.agents.extractor_agent.parse_document") as mock_parse,
        ):
            result = await agent.run(
                media_urls=["https://example.com/photo.jpg"],
                document_type="HEALTH",
            )

        mock_parse.assert_not_called()
        agent.extractor.extract_health.assert_called_once()
        assert result["data"]["policy_name"] == "Photo Policy"

    @pytest.mark.asyncio
    async def test_pdf_docling_disabled_falls_back_to_vision(self):
        """PDF + Docling disabled → vision-only fallback."""
        agent = _make_agent(
            extraction_result={"policy_name": "Vision Fallback", "sum_insured": 500000},
            triage_result='{"data_exists_in_document": false}',
        )
        with (
            patch.object(agent, "docling_enabled", False),
            patch("policydecoder.agents.extractor_agent.parse_document") as mock_parse,
        ):
            await agent.run(media_urls=[], document_type="HEALTH", input_path=str(DUMMY_PDF))

        mock_parse.assert_not_called()
        agent.extractor.extract_health.assert_called_once()

    @pytest.mark.asyncio
    async def test_pdf_missing_field_triggers_vision_fallback(self):
        """Missing field + triage confirms exists → single vision call on page."""
        agent = _make_agent(
            extraction_result={},
            text_result='{"policy_name": "Care Supreme"}',
            table_result='{"sum_insured": null}',
        )
        # Triage says the missing sum_insured exists in a page image
        triage_resp = MagicMock()
        triage_resp.choices[0].message.content = '{"data_exists_in_document": true}'
        agent.llm.chat.completions.create.side_effect = [
            # first two are text+table extraction, third is triage
            *agent.llm.chat.completions.create.side_effect,
            triage_resp,
        ]

        with (
            patch.object(agent, "docling_enabled", True),
            patch(
                "policydecoder.agents.extractor_agent.parse_document",
                return_value=_fake_parse_result(),
            ),
            patch(
                "policydecoder.docling_parser.render_page",
                return_value=Path("page1.png"),
            ),
            patch.object(
                agent.extractor,
                "extract_from_image_path",
                return_value={"sum_insured": 1500000, "annual_premium": 18000},
            ) as mock_vision,
        ):
            result = await agent.run(
                media_urls=[], document_type="HEALTH", input_path=str(DUMMY_PDF)
            )

        assert result["data"]["sum_insured"] == 1500000
        mock_vision.assert_called_once()  # single fallback page, not a loop
