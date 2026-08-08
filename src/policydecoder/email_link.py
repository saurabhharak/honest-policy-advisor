"""Pre-filled Gmail compose links.

The user sends the letter from their own email. No SMTP, no credentials.
"""

from urllib.parse import quote, urlencode

MAX_GMAIL_BODY_CHARS = 7000


def build_gmail_compose_url(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
) -> str:
    """Build a Gmail compose URL with recipient, subject, and body pre-filled."""
    safe_body = body if len(body) <= MAX_GMAIL_BODY_CHARS else body[:MAX_GMAIL_BODY_CHARS]

    params = {
        "view": "cm",
        "fs": "1",
        "to": to,
        "su": subject,
        "body": safe_body,
    }
    if cc:
        params["cc"] = cc

    query = urlencode(params, quote_via=quote)
    return f"https://mail.google.com/mail/?{query}"
