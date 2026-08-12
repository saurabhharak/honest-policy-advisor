"""Live test: run the compiled LangGraph pipeline on a real policy PDF.

Uses real Docling + real LLM + real agents, with in-memory LangGraph
backends (no Postgres needed). Prints the graph reply, analysis, and the
L0-L3 memory that was written.

Usage:
    uv run python scripts/live_test_graph.py <path-to-policy.pdf>
"""

import asyncio
import json
import sys
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from openai import OpenAI

from policydecoder.agents.extractor_agent import ExtractorAgent
from policydecoder.agents.health_analyst import HealthAnalyst
from policydecoder.agents.letter_drafter import LetterDrafter
from policydecoder.agents.life_analyst import LifeAnalyst
from policydecoder.agents.researcher_agent import ResearcherAgent
from policydecoder.config import get_config
from policydecoder.embeddings import Embedder
from policydecoder.extractor import PolicyExtractor
from policydecoder.graph.pipeline import build_graph
from policydecoder.graph.state import AgentContext, GraphContext
from policydecoder.insurer_data import get_insurer_metrics
from policydecoder.logging import configure_logging, get_logger
from policydecoder.router import heuristic_classify

logger = get_logger("policydecoder.scripts.live_test_graph")


async def main(pdf_path: str) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    configure_logging()
    config = get_config()

    llm = OpenAI(api_key=config.openai_api_key, base_url=config.openai_base_url)
    extractor = PolicyExtractor(llm)
    analyzer = None  # not needed for the media path

    from policydecoder.docling_parser import parse_document

    class RouterAgent:
        async def run(self, media_urls, input_path=None):
            if input_path:
                parsed = parse_document(Path(input_path))
                if parsed:
                    label = heuristic_classify(parsed["markdown"])
                    if label in ("HEALTH", "LIFE"):
                        return (label, 0.5)
            return ("LIFE", 0.0)

    agents = AgentContext(
        router=RouterAgent(),
        extractor_agent=ExtractorAgent(extractor=extractor, llm_client=llm),
        researcher=ResearcherAgent(llm_client=llm),
        health_analyst=HealthAnalyst(llm_client=llm, benchmark_lookup=get_insurer_metrics),
        life_analyst=LifeAnalyst(llm_client=llm),
        letter_drafter=LetterDrafter(llm_client=llm),
        analyzer=analyzer,
        llm=llm,
    )

    embedder = Embedder(llm_client=llm, model=config.embeddings_model)
    store = InMemoryStore(index={"embed": embedder, "dims": 1536})
    checkpointer = InMemorySaver()
    graph = build_graph(agents, checkpointer=checkpointer, store=store)

    print(f"Running LangGraph pipeline on: {pdf_path}")
    print(f"Docling enabled: {config.docling_enabled}")
    print(f"LLM: {config.llm_model}")
    print()

    ctx = GraphContext(
        user_id="live-test-user",
        contact="live-test@example.com",
        channel="file",
        agents=agents,
    )
    result = await graph.ainvoke(
        {
            "contact": "live-test@example.com",
            "channel": "file",
            "media_urls": [f"file://{pdf_path}"],
            "input_path": pdf_path,
            "text": "",
            "case_state": "IDLE",
        },
        {"configurable": {"thread_id": "live-test-thread"}},
        context=ctx,
    )

    print("=" * 60)
    print("REPLY:")
    print(result.get("reply", "(no reply)"))
    print("=" * 60)

    print("\n--- State (analysis / calc) ---")
    state_slim = {
        k: result.get(k)
        for k in ("document_type", "extraction", "analysis", "calc_results", "findings")
        if result.get(k)
    }
    print(json.dumps(state_slim, indent=2, ensure_ascii=False, default=str)[:4000])

    print("\n--- Memory written (L0-L3) ---")
    for ns in (
        ("live-test-user", "l0"),
        ("live-test-user", "l1", "atoms"),
        ("live-test-user", "l2", "scenarios"),
        ("live-test-user", "l3", "profile"),
    ):
        items = await store.asearch(ns)
        print(f"\n{ns}: {len(items)} item(s)")
        for it in items[:5]:
            print("  ", json.dumps(it.value, ensure_ascii=False, default=str)[:300])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/live_test_graph.py <path-to-policy.pdf>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
