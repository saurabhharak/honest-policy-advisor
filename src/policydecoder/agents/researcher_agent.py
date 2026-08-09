"""Researcher Agent — fetches live market/regulatory data with a whitelist.

Single responsibility: given a research topic, fetch relevant info from
trusted sources and return structured findings [{source, claim, url}].

Fact-drift prevention: a strict domain whitelist is enforced at the
Python layer (not just the prompt). Any fetched content whose URL is
outside ALLOWED_DOMAINS is silently dropped before it can reach an
analyst. Never blocks the core verdict — failures return empty findings.
"""

from collections.abc import Callable, Coroutine
from typing import Any

from policydecoder.agents.base import BaseAgent
from policydecoder.logging import get_logger

logger = get_logger("policydecoder.agent.researcher")

# Trusted sources only. Everything else is dropped at the Python layer.
ALLOWED_DOMAINS = {"irdai.gov.in", "joinditto.in", "beshak.org"}

# Topic -> list of candidate URLs (all within ALLOWED_DOMAINS).
TOPIC_URLS: dict[str, list[str]] = {
    "care_health_csr": [
        "https://joinditto.in/articles/general/irdai-annual-report/",
    ],
    "how_to_choose_health": [
        "https://joinditto.in/articles/health-insurance/how-to-choose-health-insurance/",
    ],
    "how_to_choose_term": [
        "https://joinditto.in/articles/life-insurance/important-factors-to-consider-when-purchasing-term-insurance/",
    ],
    "best_health_plans": [
        "https://joinditto.in/health-insurance/best-health-plans-in-india/",
    ],
    "best_term_plans": [
        "https://joinditto.in/term-insurance/best-term-plans-in-india/",
    ],
    "irdai_report": ["https://irdai.gov.in/annual-report"],
}

_HTTP_FETCH: Callable[..., Coroutine] | None = None


def _is_allowed(url: str | None) -> bool:
    """Whether a URL's domain is in the whitelist."""
    if not url:
        return False
    from urllib.parse import urlparse

    domain = urlparse(url).hostname or ""
    return any(domain == d or domain.endswith(f".{d}") for d in ALLOWED_DOMAINS)


class ResearcherAgent(BaseAgent):
    """Fetches trusted information and returns whitelisted findings."""

    def __init__(
        self,
        llm_client,
        model: str | None = None,
        fetch_fn: Callable[..., Coroutine] | None = None,
    ):
        super().__init__(llm_client, model)
        self.fetch = fetch_fn or _default_fetch

    async def run(  # type: ignore[override]
        self, topic: str, **inputs: Any
    ) -> list[dict[str, Any]]:
        urls = TOPIC_URLS.get(topic, [])
        if not urls:
            return []

        findings: list[dict[str, Any]] = []
        for url in urls:
            if not _is_allowed(url):
                continue  # never fetch a non-whitelisted URL
            content = await self._fetch_safe(url)
            if not content:
                continue
            claim = self._summarize(url, content)
            if claim:
                findings.append({"source": url, "claim": claim, "url": url})
        return findings

    async def _fetch_safe(self, url: str) -> str | None:
        """Fetch a URL, returning None on any failure (never raises)."""
        try:
            result = await self.fetch(url)
            if result is None:
                return None
            # If fetch returns a response-like object, extract .text
            text = getattr(result, "text", None)
            if text is None:
                text = result if isinstance(result, str) else str(result)
            return text
        except Exception as e:
            self.logger.warning("Fetch failed for %s: %s", url, e)
            return None

    def _summarize(self, url: str, content: str) -> str | None:
        """Extract the key claim from fetched content via a short LLM summary.

        Strips HTML tags, then asks the LLM for a 1-2 sentence factual
        summary so findings carry clean, attributable claims instead of
        raw page text.
        """
        import re

        text = content.strip()
        if not text:
            return None
        # Strip HTML tags + collapse whitespace (the HTTP fallback returns raw HTML).
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return None

        prompt = (
            "Summarize the following web page content into 1-2 factual sentences "
            "about insurance. Return ONLY the summary text, no preamble.\n\n"
            f"PAGE CONTENT (first 3000 chars):\n{text[:3000]}"
        )
        summary = self.generate("You are a research summarizer.", prompt, timeout=15)
        summary = summary.strip()
        if not summary:
            return text[:200]  # LLM failed — fall back to naive truncation
        return summary[:400]


async def _default_fetch(url: str):
    """Default fetch: try the MCP fetch tool, fall back to HTTP."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        return await _http_fetch(url)

    # Try MCP fetch server if configured (matches the .mcp.json setup)
    try:
        server_params = StdioServerParameters(command="uvx", args=["mcp-server-fetch"])
        async with (
            stdio_client(server_params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool("fetch", {"url": url, "max_length": 5000})
            if result and getattr(result, "content", None):
                return "\n".join(
                    str(part.text) for part in result.content if getattr(part, "text", None)
                )
    except Exception as e:
        logger.warning("MCP fetch failed for %s, falling back to HTTP: %s", url, e)
    return await _http_fetch(url)


async def _http_fetch(url: str) -> str:
    """Plain HTTP fallback (requests is already a dependency)."""
    import requests

    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.text
