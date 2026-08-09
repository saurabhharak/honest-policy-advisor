"""Run the full multi-agent pipeline on a local policy file.

Usage:
    uv run python scripts/run_policy_file.py <path-to-policy.pdf>

This bypasses the chat channels and runs the extractor → analyst →
report pipeline directly on a file, for testing with real policy PDFs.
"""

import asyncio
import json
import sys
from pathlib import Path

from openai import OpenAI

from policydecoder.agents.extractor_agent import ExtractorAgent
from policydecoder.agents.health_analyst import HealthAnalyst
from policydecoder.agents.life_analyst import LifeAnalyst
from policydecoder.agents.researcher_agent import ResearcherAgent
from policydecoder.config import get_config
from policydecoder.extractor import PolicyExtractor
from policydecoder.insurer_data import get_insurer_metrics
from policydecoder.logging import configure_logging, get_logger
from policydecoder.supervisor import Supervisor

logger = get_logger("policydecoder.scripts.run_policy_file")


async def main(pdf_path: str) -> None:
    configure_logging()
    config = get_config()
    llm = OpenAI(api_key=config.openai_api_key, base_url=config.openai_base_url)
    extractor = PolicyExtractor(llm)

    from policydecoder.router import classify_document

    class RouterAgent:
        async def run(self, media_urls, input_path=None):
            # For a local file we default to LIFE unless Docling tells us otherwise.
            return ("LIFE", 0.5)

    supervisor = Supervisor(
        router=RouterAgent(),
        extractor=ExtractorAgent(extractor=extractor, llm_client=llm),
        researcher=ResearcherAgent(llm_client=llm),
        health_analyst=HealthAnalyst(
            llm_client=llm, benchmark_lookup=get_insurer_metrics
        ),
        life_analyst=LifeAnalyst(llm_client=llm),
        letter_drafter=None,
    )

    print(f"Running pipeline on: {pdf_path}")
    print(f"Docling enabled: {config.docling_enabled}")
    print()

    result = await supervisor.process_media(
        media_urls=[], conversation_id="local-file-test", channel="file",
        input_path=pdf_path,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/run_policy_file.py <path-to-policy.pdf>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
