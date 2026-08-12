"""Live test: LangGraph pipeline with REAL Postgres backends on the policy PDF.

Mirrors main.py: builds backends via create_backends (pool + vector ext +
setup), UserStore, compiles the graph with the Postgres checkpointer/store,
and runs the media pipeline on a real policy PDF.

Usage:
    uv run python scripts/live_test_postgres.py <path-to-policy.pdf>
"""

import asyncio
import json
import selectors
import sys
from pathlib import Path

from openai import OpenAI

from policydecoder.agents.extractor_agent import ExtractorAgent
from policydecoder.agents.health_analyst import HealthAnalyst
from policydecoder.agents.letter_drafter import LetterDrafter
from policydecoder.agents.life_analyst import LifeAnalyst
from policydecoder.agents.researcher_agent import ResearcherAgent
from policydecoder.config import get_config
from policydecoder.docling_parser import parse_document
from policydecoder.embeddings import Embedder
from policydecoder.extractor import PolicyExtractor
from policydecoder.graph.backends import close_backends, create_backends
from policydecoder.graph.identity import UserStore
from policydecoder.graph.pipeline import build_graph
from policydecoder.graph.state import AgentContext, GraphContext
from policydecoder.insurer_data import get_insurer_metrics
from policydecoder.logging import configure_logging, get_logger
from policydecoder.router import heuristic_classify

logger = get_logger("policydecoder.scripts.live_test_postgres")


async def main(pdf_path: str) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    configure_logging()
    config = get_config()

    llm = OpenAI(api_key=config.openai_api_key, base_url=config.openai_base_url)
    extractor = PolicyExtractor(llm)

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
        analyzer=None,
        llm=llm,
    )

    embedder = Embedder(llm_client=llm, model=config.embeddings_model)

    print(f"=== Postgres backends ({config.database_url.split('@')[-1]}) ===")
    backends = await create_backends(
        config.database_url,
        embed=embedder,
        dims=1536,
        pool_size=config.postgres_pool_size,
    )
    print("Backends ready: checkpointer + store setup() done")

    user_store = UserStore(backends.pool)
    await user_store.setup()
    print("UserStore ready (users table ensured)")

    # Seed per-product rubrics so the rubric triage path can load them.
    from policydecoder.graph.prompt_store import seed_rubrics

    await seed_rubrics(backends.store)
    print("Rubrics seeded into store")

    graph = build_graph(agents, checkpointer=backends.checkpointer, store=backends.store)

    # Reuse a fixed identity so memory persists across runs.
    user_id = await user_store.get_or_create("live-test@example.com", "file")
    print(f"user_id: {user_id}")

    ctx = GraphContext(
        user_id=user_id,
        contact="live-test@example.com",
        channel="file",
        agents=agents,
    )

    print(f"\nRunning LangGraph pipeline (Postgres + rubric triage) on: {pdf_path}")
    print(f"Docling enabled: {config.docling_enabled}")
    print(f"LLM: {config.llm_model}")
    print()

    result = await graph.ainvoke(
        {
            "contact": "live-test@example.com",
            "channel": "file",
            "media_urls": [f"file://{pdf_path}"],
            "input_path": pdf_path,
            "text": "",
            "case_state": "IDLE",
            "use_rubric_triage": True,
        },
        {"configurable": {"thread_id": "live-postgres-thread"}},
        context=ctx,
    )

    print("=" * 60)
    print("REPLY:")
    print(result.get("reply", "(no reply)"))
    print("=" * 60)

    print("\n--- Rubric triage outputs ---")
    extraction = result.get("extraction") or {}
    print("EXTRACTION:", json.dumps(extraction, ensure_ascii=False, default=str)[:1500])
    calc = result.get("calc_results") or {}
    print("CALC:", json.dumps(calc, ensure_ascii=False, default=str)[:800])
    verdict = result.get("layman_verdict") or {}
    print("LAYMAN VERDICT:", json.dumps(verdict, ensure_ascii=False, default=str)[:2000])

    print("\n--- Memory written to Postgres (L0-L3) ---")
    for ns in (
        (user_id, "l0"),
        (user_id, "l1", "atoms"),
        (user_id, "l2", "scenarios"),
        (user_id, "l3", "profile"),
    ):
        items = await backends.store.asearch(ns)
        print(f"\n{ns}: {len(items)} item(s)")
        for it in items[:5]:
            print("  ", json.dumps(it.value, ensure_ascii=False, default=str)[:250])

    await close_backends(backends)
    print("\nBackends closed cleanly.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/live_test_postgres.py <path-to-policy.pdf>")
        sys.exit(1)
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main(sys.argv[1]))
    finally:
        loop.close()
