"""Docling parser wrapper — PDF → structured markdown/tables.

A tool, not an agent. Parses a local PDF via IBM Docling (layout +
TableFormer + OCR) and returns chunkable markdown, structured tables
JSON, and page image paths for the extractor agent to route.

GPU memory: the converter is created per parse and explicitly torn
down afterwards (del + torch.cuda.empty_cache) — no persistent
singleton pinning VRAM. Opt-in via DOCLING_ENABLED; lazy import so the
core app runs without docling installed.
"""

import contextlib
from pathlib import Path
from typing import Any

from policydecoder.config import get_config
from policydecoder.logging import get_logger
from policydecoder.opik_tracing import trace_llm

logger = get_logger("policydecoder.docling")


def is_enabled() -> bool:
    """Whether Docling parsing is active (DOCLING_ENABLED=true)."""
    return get_config().docling_enabled


def parse_document(input_path: Path) -> dict[str, Any] | None:
    """Parse a PDF with Docling. Per-parse lifecycle (no singleton).

    Returns {markdown, tables_json, page_images, page_count,
    pages_with_tables} or None when disabled/failed.
    """
    if not is_enabled():
        return None
    try:
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter(pipeline_options=_pipeline_options())
        try:
            result = converter.convert(str(input_path))
            return _to_result(result, input_path)
        finally:
            del converter
            _free_gpu()
    except Exception as e:
        logger.warning("Docling parse failed for %s: %s", input_path, e)
        return None


def _to_result(result, input_path: Path) -> dict[str, Any]:
    """Convert a DoclingDocument into the chunkable result shape."""
    doc = getattr(result, "document", result)

    markdown = ""
    if hasattr(doc, "export_to_markdown"):
        markdown = doc.export_to_markdown()

    tables_json: list[Any] = []
    pages_with_tables: list[int] = []
    # Docling tables live under document.tables / OCR tables; collect
    # what's available and record which page each came from.
    if hasattr(doc, "tables"):
        for t in doc.tables:
            with contextlib.suppress(Exception):
                tables_json.append(t.export_to_dict())

    page_count = len(getattr(doc, "pages", [])) or 1

    trace_llm(
        "docling_parse",
        model="docling",
        input_text=f"path={input_path.name}",
        output_text=f"pages={page_count}, tables={len(tables_json)}",
        metadata={"page_count": page_count, "table_count": len(tables_json)},
    )

    return {
        "markdown": markdown,
        "tables_json": tables_json,
        "page_images": [],  # populated by the extractor agent if needed
        "page_count": page_count,
        "pages_with_tables": pages_with_tables,
    }


def _pipeline_options() -> Any:
    """Build Docling pipeline options with CUDA accelerator when available."""
    try:
        from docling.datamodel.pipeline_options import (
            AcceleratorDevice,
            AcceleratorOptions,
            PdfPipelineOptions,
        )

        opts = PdfPipelineOptions()
        opts.do_table_structure = True  # TableFormer

        if _cuda_available():
            opts.accelerator_options = AcceleratorOptions(
                num_threads=4, device=AcceleratorDevice.CUDA
            )
        else:
            opts.accelerator_options = AcceleratorOptions(
                num_threads=4, device=AcceleratorDevice.CPU
            )
        return opts
    except Exception as e:
        logger.warning("Docling pipeline options unavailable: %s", e)
        return None


def _cuda_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except ImportError:
        return False


def _free_gpu() -> None:
    """Release GPU memory after a parse. No-op on CPU."""
    if not _cuda_available():
        return
    try:
        import torch

        torch.cuda.empty_cache()
    except Exception as e:
        logger.warning("Failed to free GPU cache: %s", e)
