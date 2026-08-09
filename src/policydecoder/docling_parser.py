"""Docling parser wrapper — PDF → structured markdown/tables.

A tool, not an agent. Parses a local PDF via IBM Docling (layout +
TableFormer + OCR) and returns chunkable markdown, structured tables
JSON, and page image paths for the extractor agent to route.

GPU memory: the converter is created per parse and explicitly torn
down afterwards (del + torch.cuda.empty_cache) — no persistent
singleton pinning VRAM. Opt-in via DOCLING_ENABLED; lazy import so the
core app runs without docling installed.
"""

from pathlib import Path
from typing import Any

from policydecoder.config import get_config
from policydecoder.logging import get_logger
from policydecoder.opik_tracing import trace_llm

logger = get_logger("policydecoder.docling")


def is_enabled() -> bool:
    """Whether Docling parsing is active (DOCLING_ENABLED=true)."""
    return get_config().docling_enabled


# In-memory parse cache keyed by (path, mtime) so the router and the
# extractor reuse one Docling run per file instead of parsing twice.
_PARSE_CACHE: dict[tuple[str, float], dict[str, Any]] = {}
_MAX_CACHE_ENTRIES = 8


def parse_document(input_path: Path) -> dict[str, Any] | None:
    """Parse a PDF with Docling. Per-parse lifecycle (no singleton).

    Returns {markdown, tables_json, page_images, page_count,
    pages_with_tables} or None when disabled/failed. Results are cached
    per (path, mtime) so repeated calls in one process don't re-run the
    heavy model.
    """
    if not is_enabled():
        return None
    try:
        key = _cache_key(input_path)
        if key in _PARSE_CACHE:
            return _PARSE_CACHE[key]

        # Disable torch inductor (needs MSVC cl.exe on Windows CPU).
        import os

        os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")
        os.environ.setdefault("TORCHINDUCTOR_DISABLE", "1")

        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import DocumentConverter, PdfFormatOption

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=_pipeline_options()),
            }
        )
        try:
            result = converter.convert(str(input_path))
            parsed = _to_result(result, input_path)
        finally:
            del converter
            _free_gpu()

        if parsed is not None:
            _PARSE_CACHE[key] = parsed
            if len(_PARSE_CACHE) > _MAX_CACHE_ENTRIES:
                _PARSE_CACHE.pop(next(iter(_PARSE_CACHE)))
        return parsed
    except Exception as e:
        logger.warning("Docling parse failed for %s: %s", input_path, e)
        return None


def _cache_key(input_path: Path) -> tuple[str, float]:
    """Cache key = (absolute path, mtime)."""
    try:
        mtime = input_path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (str(input_path.resolve()), mtime)


def _to_result(result, input_path: Path) -> dict[str, Any]:
    """Convert a DoclingDocument into the chunkable result shape."""
    doc = getattr(result, "document", result)

    markdown = ""
    if hasattr(doc, "export_to_markdown"):
        markdown = doc.export_to_markdown()

    # TableFormer tables surface in the markdown as pipe-table blocks in
    # this Docling version (doc.tables is empty). Parse them out so the
    # extractor agent can feed structured tables to the table-field LLM.
    tables_json = _extract_pipe_tables(markdown)

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
        "pages_with_tables": list(range(1, page_count + 1)),
    }


def _extract_pipe_tables(markdown: str) -> list[dict[str, Any]]:
    """Parse markdown pipe-table blocks into structured table dicts.

    A block is consecutive lines starting with '|'. Returns a list of
    {"header": [...], "rows": [[...], ...]} dicts.
    """
    tables: list[dict[str, Any]] = []
    current: list[list[str]] = []

    def flush() -> None:
        nonlocal current
        if len(current) >= 2:  # header + at least one data row
            header = current[0]
            rows = current[1:]
            tables.append({"header": header, "rows": rows})
        current = []

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            # Skip separator rows (e.g. |---|----|)
            if cells and all(set(c) <= set("-: ") for c in cells):
                continue
            current.append(cells)
        else:
            flush()
    flush()
    return tables


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
