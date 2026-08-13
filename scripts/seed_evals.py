"""Seed the eval harness: build the Docling cache + push gold datasets to Opik.

Usage:
    uv run python scripts/seed_evals.py            # docling cache + datasets
    uv run python scripts/seed_evals.py --cache-only
    uv run python scripts/seed_evals.py --datasets-only

Docling cache: parses every insurance_policies/*.pdf once and stores the
result at src/policydecoder/evals/data/docling_cache/<stem>.json so the
metric loop never re-runs Docling/OCR. Datasets: clear() + insert() each
agent's gold rows so the dataset is pinned to the current gold version.
"""

import argparse
import json
import sys
from pathlib import Path

from policydecoder.evals.config import get_opik_client
from policydecoder.evals.data import GOLD_FILES, save_docling_cache
from policydecoder.evals.datasets import seed_dataset

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICIES_DIR = REPO_ROOT / "insurance_policies"


def build_docling_cache() -> dict[str, Path]:
    """Parse every policy PDF into the cache. Returns {stem: cache_path}."""
    from policydecoder.docling_parser import parse_document

    pdfs = sorted(POLICIES_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {POLICIES_DIR}")
        return {}
    print(f"Parsing {len(pdfs)} PDFs with Docling (one-time)...")
    written: dict[str, Path] = {}
    for pdf in pdfs:
        print(f"  {pdf.name} ...", flush=True)
        result = parse_document(pdf)
        if result is None:
            print("    FAILED (skipped)")
            continue
        path = save_docling_cache(pdf, result)
        written[pdf.stem] = path
        print(f"    cached -> {path.name} ({len(result.get('markdown', ''))} chars)")
    return written


def seed_all_datasets() -> None:
    client = get_opik_client()
    if client is None:
        print("Opik not available (OPIK_ENABLED false or unreachable); skipping dataset seeding.")
        return
    for agent, path in GOLD_FILES.items():
        with open(path, encoding="utf-8") as f:
            gold = json.load(f)
        rows = gold.get("rows", [])
        print(f"Seeding {agent} ({len(rows)} rows, v{gold.get('version', 1)}) ...")
        seed_dataset(client, agent, rows)
    print("Datasets seeded.")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Seed eval gold datasets + docling cache.")
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--datasets-only", action="store_true")
    args = parser.parse_args()

    if not args.datasets_only:
        build_docling_cache()
    if not args.cache_only:
        seed_all_datasets()


if __name__ == "__main__":
    main()
