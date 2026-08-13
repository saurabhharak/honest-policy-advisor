"""Gold datasets + Docling cache for the eval harness.

Gold JSON files are the source of truth: each carries {"version": N,
"rows": [...]}. The Docling cache stores pre-parsed PDF results so the
metric loop never re-runs Docling/OCR.
"""

import json
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).parent
_DOCLING_CACHE_DIR = _DATA_DIR / "docling_cache"

GOLD_FILES: dict[str, Path] = {
    "router": _DATA_DIR / "router_gold.json",
    "extractor": _DATA_DIR / "extractor_gold.json",
    "researcher": _DATA_DIR / "researcher_gold.json",
    "health_analyst": _DATA_DIR / "health_analyst_gold.json",
    "life_analyst": _DATA_DIR / "life_analyst_gold.json",
    "letter_drafter": _DATA_DIR / "letter_gold.json",
}


def load_gold(agent: str) -> dict[str, Any]:
    """Load a gold dataset file: {"version": N, "rows": [...]}."""
    path = GOLD_FILES[agent]
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def gold_version(agent: str) -> int:
    return int(load_gold(agent).get("version", 1))


def gold_rows(agent: str) -> list[dict[str, Any]]:
    return list(load_gold(agent).get("rows", []))


def load_docling_cache(pdf_path: str | Path | None) -> dict[str, Any] | None:
    """Return the cached Docling parse result for a PDF, or None.

    Cache file name = <pdf_stem>.json inside data/docling_cache/.
    """
    if not pdf_path:
        return None
    stem = Path(pdf_path).stem
    cache_file = _DOCLING_CACHE_DIR / f"{stem}.json"
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_docling_cache(pdf_path: str | Path, result: dict[str, Any]) -> Path:
    """Persist a Docling parse result to the cache. Returns the cache path."""
    _DOCLING_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _DOCLING_CACHE_DIR / f"{Path(pdf_path).stem}.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    return cache_file
