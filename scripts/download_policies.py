"""Download real insurance policy specimen PDFs from insurer sites.

Uses Playwright to handle JS-heavy insurer pages. For each target URL,
it loads the page, collects all .pdf links plus JS download links, and
saves them into insurance_policies/ with a readable name.

Usage:
    uv run python scripts/download_policies.py

Targets are defined in TARGETS below. Each entry: (url, category,
save_prefix). Only whitelisted categories are saved (term, life,
endowment, ulip, health). Existing files are skipped.
"""

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_DIR = Path(__file__).resolve().parent.parent / "insurance_policies"

# (page_url, category, filename_prefix)
TARGETS = [
    # Term insurance specimen policy bonds
    ("https://www.hdfclife.com/policy-documents", "term", "hdfc_term"),
    ("https://www.iciciprulife.com/services/download-centre.html", "term", "icici_term"),
    ("https://www.tataaia.com/policy-documents.html", "term", "tataaia_term"),
    # Endowment / ULIP
    ("https://www.hdfclife.com/policy-documents", "endowment", "hdfc_savings"),
    ("https://www.iciciprulife.com/services/download-centre.html", "ulip", "icici_ulip"),
    # Health (second type — family floater)
    ("https://www.careinsurance.com/other-downloads.html", "health", "care_health"),
    (
        "https://www.bajajgeneralinsurance.com/health-insurance-plans/health-insurance-documents.html",
        "health",
        "bajaj_health",
    ),
]

ALLOWED_CATEGORIES = {"term", "life", "endowment", "ulip", "health"}

# Ignore these in filenames so saved names stay readable
NOISE_WORDS = [
    "policy",
    "document",
    "bond",
    "specimen",
    "wording",
    "insurance",
    "sample",
    "download",
    "brochure",
    "plan",
    "english",
    "-",
    "_",
]


def sanitize_name(category: str, url: str, prefix: str) -> str:
    """Build a readable filename from the URL + category."""
    stem = Path(url.split("?")[0]).stem or "policy"
    for w in NOISE_WORDS:
        stem = stem.replace(w, " ")
    stem = re.sub(r"\s+", " ", stem).strip().replace(" ", "_")
    if not stem:
        stem = "policy"
    return f"{prefix}_{stem}_{category}.pdf"


def is_pdf_url(url: str) -> bool:
    return ".pdf" in url.lower()


def download_pdfs(page, url: str, category: str, prefix: str) -> list[Path]:
    """Load a page, find PDF links, download them. Returns saved paths."""
    saved: list[Path] = []
    print(f"\n=== {category.upper()} :: {url} ===")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)  # let JS render

    # Collect candidate hrefs (direct PDFs + JS download links)
    hrefs = page.eval_on_selector_all(
        "a",
        "els => els.map(e => e.href).filter(h => h && h.includes('.pdf'))",
    )
    # Also grab links whose text hints at a policy/specimen
    text_links = page.eval_on_selector_all(
        "a",
        "els => els.map(e => ({href: e.href, text: (e.innerText||'').toLowerCase()})).filter(x => x.href && (x.text.includes('policy') || x.text.includes('specimen') || x.text.includes('wording')))",
    )

    candidates = list(dict.fromkeys(hrefs))  # dedupe, keep order
    print(f"  found {len(candidates)} direct PDF links, {len(text_links)} text-matched")

    if not candidates:
        print("  no direct PDF links found on this page.")
        return saved

    # Download the first few that match a category keyword in the URL
    keywords = {
        "term": ["term", "protect", "life"],
        "endowment": ["endowment", "jeevan", "sanchy", "savings", "achieve"],
        "ulip": ["ulip", "invest", "wealth", "signature", "fortune"],
        "health": ["health", "care", "supreme", "floater", "optima"],
    }
    wanted = keywords.get(category, [])
    picked = [c for c in candidates if any(k in c.lower() for k in wanted)]
    picked = picked[:3] or candidates[:2]

    for i, pdf_url in enumerate(picked):
        fname = (
            sanitize_name(category, pdf_url, prefix)
            if len(picked) == 1
            else (f"{prefix}_{category}_{i + 1}.pdf")
        )
        out_path = OUT_DIR / fname
        if out_path.exists():
            print(f"  skip (exists): {fname}")
            continue
        try:
            # Download via the page context (handles redirects/cookies)
            resp = page.request.get(pdf_url, timeout=60000)
            if resp.ok and resp.headers.get("content-type", "").startswith("application/pdf"):
                out_path.write_bytes(resp.body())
                saved.append(out_path)
                print(f"  saved: {fname} ({len(resp.body())} bytes)")
            else:
                print(f"  not a PDF ({resp.status}): {pdf_url[:80]}")
        except Exception as e:
            print(f"  failed: {pdf_url[:80]} -> {e}")
    return saved


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_saved: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True)
        try:
            for url, category, prefix in TARGETS:
                if category not in ALLOWED_CATEGORIES:
                    continue
                all_saved.extend(download_pdfs(page, url, category, prefix))
        finally:
            browser.close()

    print(f"\n=== Done. {len(all_saved)} PDFs saved to {OUT_DIR} ===")
    for f in all_saved:
        print(f"  {f}")


if __name__ == "__main__":
    sys.exit(main())
