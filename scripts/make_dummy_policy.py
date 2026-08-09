"""Generate a sanitized 3-page dummy policy PDF for tests.

A minimal, dependency-free PDF writer producing a text-based 3-page
policy document (no external libs needed). Committed output lives in
tests/assets/dummy_policy.pdf so the test suite is portable (no
absolute paths, no runtime generation).
"""

from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent.parent / "tests" / "assets"
OUTPUT = ASSETS_DIR / "dummy_policy.pdf"


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _page(content_lines: list[str], page_number: int) -> bytes:
    """Build one PDF page object with simple text content."""
    lines = ["BT /F1 12 Tf 50 750 Td 14 TL"]
    for line in content_lines:
        lines.append(f"({_escape(line)}) Tj T*")
    lines.append("ET")
    stream = "\n".join(lines)
    length = len(stream.encode("latin-1"))

    return (
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        f"/Contents {page_number + 4} 0 R >>\n"
    ).encode("latin-1")


def build_pdf() -> bytes:
    """Assemble a minimal 3-page PDF."""
    pages = [
        [
            "Health Insurance Policy - Sample Plan",
            "Policy Name: Sample Health Secure",
            "Insurer: Sample Health Insurance",
            "Annual Premium: Rs 18,000",
            "Sum Insured: Rs 15,00,000",
            "Policy Start Date: 2024-01-01",
        ],
        [
            "Room Rent Cap: No cap",
            "Co-pay: 10%",
            "Waiting Period: 30 days (accident), 3 years (pre-existing)",
            "Restoration: Unlimited",
            "Network Hospitals: 12,000",
        ],
        [
            "Exclusions: Maternity, Pre-existing",
            "Free Look Period: 15 days",
            "This is a dummy policy for testing only.",
        ],
    ]

    # Object 1: catalog, 2: pages, 3: font, 4-6: page contents
    catalog = b"<< /Type /Catalog /Pages 2 0 R >>\n"
    pages_obj = (
        b"<< /Type /Pages /Kids [4 0 R 5 0 R 6 0 R] /Count 3 >>\n"
    )
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"

    content_streams = []
    for i, content in enumerate(pages):
        lines = ["BT /F1 12 Tf 50 750 Td 14 TL"]
        for line in content:
            lines.append(f"({_escape(line)}) Tj T*")
        lines.append("ET")
        stream = "\n".join(lines)
        content_streams.append(
            f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream\n"
        )

    body = b"%PDF-1.4\n"
    objects = [catalog, pages_obj, font]
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
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode("latin-1")
    return body


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(build_pdf())
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
