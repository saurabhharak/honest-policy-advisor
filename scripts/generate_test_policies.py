"""Generate synthetic, fully-populated policy PDFs for testing.

The publicly-downloaded specimen policies identify the product but leave
the schedule blank (<< >> placeholders). This script takes the real
wording markdown, replaces the placeholder schedule with realistic
filled-in values, and produces a proper multi-page PDF per category so
the full pipeline (router → Docling → extractor → analyst) is exercised
with real numbers.

Usage:
    uv run python scripts/generate_test_policies.py

Outputs to insurance_policies/synthetic/<category>_<name>.pdf
"""

from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SOURCES = {
    "ulip": BASE / "insurance_policies" / "hdfc_savings_endowment_2.pdf",  # Click 2 Invest Plus
    "endowment": BASE / "insurance_policies" / "hdfc_savings_endowment_3.pdf",
    "health": BASE / "insurance_policies" / "bajaj_health_health_2.pdf",
}
OUT_DIR = BASE / "insurance_policies" / "synthetic"

# Realistic filled-in schedules per category. These replace the << >> placeholders.
SCHEDULES = {
    "ulip": {
        "policy_name": "HDFC Life Click 2 Invest Plus",
        "annual_premium": 75000,
        "sum_assured": 1000000,  # sum assured
        "premium_term_years": 10,
        "policy_term_years": 20,
        "maturity_value_at_8pct": 2450000,
        "maturity_value_at_4pct": 1650000,
        "premium_frequency": "Annual",
        "policy_start_date": "2021-06-15",
        "free_look_period_days": 15,
        "fund_management_charge": "1.35% p.a.",
        "premium_allocation_charge": "5% in year 1",
    },
    "endowment": {
        "policy_name": "HDFC Life Sanchay Plus",
        "annual_premium": 50000,
        "sum_assured": 750000,
        "premium_term_years": 15,
        "policy_term_years": 15,
        "maturity_value_at_8pct": 1380000,
        "maturity_value_at_4pct": 980000,
        "premium_frequency": "Annual",
        "policy_start_date": "2019-03-01",
        "free_look_period_days": 15,
        "bonus_rate": "4% per annum",
    },
    "health": {
        "policy_name": "Bajaj Health Comprehensive",
        "annual_premium": 18500,
        "sum_insured": 1000000,  # sum insured
        "room_rent_cap": "2% of Sum Insured per day",
        "co_pay_pct": 10,
        "premium_term_years": 1,
        "policy_term_years": 1,
        "waiting_accident_days": 30,
        "waiting_preexisting_years": 3,
        "restoration": "Unlimited",
        "network_hospitals": 8000,
        "policy_start_date": "2024-07-01",
        "free_look_period_days": 15,
    },
}

# The placeholder patterns found in the real specimen wordings.
PLACEHOLDERS = [
    ("<<Policyholder's Name>>", "Amit Sharma"),
    ("<<Policyholder's Date of Birth>>", "1990-04-12"),
    ("<<Policy No>>", "12345678"),
    ("<<dd/mm/yyyy>>", "2024-07-01"),
    ("<<dd/month>>", "01 July"),
    ("<<>>", "REPLACE_ME"),  # generic placeholder, handled per-field below
]


def fill_schedule(markdown: str, category: str) -> str:
    """Replace placeholders in the real wording with schedule values."""
    s = SCHEDULES[category]
    md = markdown

    # Named placeholders first
    md = md.replace("<<Policyholder's Name>>", "Amit Sharma")
    md = md.replace("<<Policyholder's Date of Birth>>", "1990-04-12")

    # Field-specific replacements (match by the label preceding the <<>>)
    field_map = {
        "Sum Assured": f"Rs. {s.get('sum_assured', 0):,}",
        "Annualized Premium": f"Rs. {s.get('annual_premium', 0):,}",
        "Single Premium": f"Rs. {s.get('annual_premium', 0):,}",
        "Premium Paying Term": f"{s.get('premium_term_years', 0)} years",
        "Policy Term": f"{s.get('policy_term_years', 0)} years",
        "Premium per Frequency": f"Rs. {s.get('annual_premium', 0):,}",
        "Total Premium per Frequency": f"Rs. {s.get('annual_premium', 0):,}",
        "Maturity Date": s.get("policy_start_date", "2024-07-01"),
        "Final Premium Due Date": s.get("policy_start_date", "2024-07-01"),
        "Frequency of Premium Payment": s.get("premium_frequency", "Annual"),
    }
    for label, value in field_map.items():
        # Replace the placeholder on the same table row as the label
        lines = md.split("\n")
        for i, line in enumerate(lines):
            if label in line and "<<" in line:
                # Replace any <<...>> cell after the label with the value
                lines[i] = line.replace("<<>>>", value).replace("<<>>", value)
        md = "\n".join(lines)

    # Fix "Rs. Rs. 75,000" duplication from partially-filled cells
    md = md.replace("Rs. Rs. ", "Rs. ")

    # Append a benefit illustration (real policies ship with one).
    md += _benefit_illustration(s)

    return md


def _benefit_illustration(s: dict) -> str:
    """Append a realistic benefit-illustration summary for life policies."""
    if "maturity_value_at_8pct" not in s:
        return ""
    prem = s.get("annual_premium", 0)
    term = s.get("policy_term_years", 0)
    mat4 = s.get("maturity_value_at_4pct", 0)
    mat8 = s.get("maturity_value_at_8pct", 0)
    return (
        "\n\n## Benefit Illustration\n\n"
        f"Maturity Value at 4%: Rs. {mat4:,}\n"
        f"Maturity Value at 8%: Rs. {mat8:,}\n"
        f"Policy Term: {term} years\n"
        f"Annual Premium: Rs. {prem:,}\n"
        "\nThe above are illustrative values, not guaranteed. "
        "Actual returns depend on fund performance and charges.\n"
    )


def md_to_pdf(md_text: str, out_path: Path) -> None:
    """Render markdown text into a multi-page PDF using reportlab-free approach.

    We use pypdfium2's PDF builder? It doesn't build PDFs. Instead we
    write a simple text-based PDF (same minimal writer as the dummy asset).
    """
    # Simple text PDF: one page per ~40 lines.
    pages = [md_text.split("\n")[i : i + 40] for i in range(0, len(md_text.split("\n")), 40)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(_build_pdf(pages))


def _escape(text: str) -> str:
    # Replace non-latin-1 chars (bullets, ₹, em-dashes) with safe ASCII
    text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _build_pdf(pages: list[list[str]]) -> bytes:
    """Build a minimal text PDF with proper page objects.

    Structure (matches the proven dummy generator):
    obj 1: catalog, obj 2: pages tree, obj 3: font,
    obj 4..N: one /Type /Page object per page, each referencing a
    following content-stream object.
    """
    n = len(pages)
    # Page objects are 4..3+n, content streams follow after.
    first_page_obj = 4
    first_stream_obj = first_page_obj + n

    catalog = b"<< /Type /Catalog /Pages 2 0 R >>\n"
    kids = " ".join(f"{first_page_obj + i} 0 R" for i in range(n))
    pages_obj = f"<< /Type /Pages /Kids [{kids}] /Count {n} >>\n".encode("latin-1")
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"

    # Page objects
    page_objs = []
    for i in range(n):
        page_objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {first_stream_obj + i} 0 R /Resources << /Font << /F1 3 0 R >> >> >>\n"
        )

    # Content streams
    content_streams = []
    for content in pages:
        lines = ["BT /F1 8 Tf 40 760 Td 10 TL"]
        for line in content:
            truncated = line[:200]  # wide enough for schedule rows
            lines.append(f"({_escape(truncated)}) Tj T*")
        lines.append("ET")
        stream = "\n".join(lines)
        content_streams.append(
            f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream\n"
        )

    body = b"%PDF-1.4\n"
    objects: list[bytes] = [catalog, pages_obj, font]
    for po in page_objs:
        objects.append(po.encode("latin-1"))
    for cs in content_streams:
        objects.append(cs.encode("latin-1"))

    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{i} 0 obj\n".encode("latin-1")
        body += obj
        body += b"endobj\n"

    xref_pos = len(body)
    body += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    body += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        body += f"{off:010d} 00000 n \n".encode("latin-1")
    body += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode("latin-1")
    return body


def main() -> None:
    from policydecoder.docling_parser import parse_document

    for category, source in SOURCES.items():
        print(f"=== {category.upper()} ===")
        parsed = parse_document(source)
        if parsed is None:
            print(f"  parse failed for {source.name}")
            continue
        md = parsed["markdown"]
        filled = fill_schedule(md, category)
        out = OUT_DIR / f"{category}_synthetic.pdf"
        md_to_pdf(filled, out)
        print(f"  generated {out} ({out.stat().st_size} bytes)")
    print("\nDone.")


if __name__ == "__main__":
    main()
