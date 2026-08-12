"""Trigger the real handler flow against the local PDF, replicating _handle_graph.

Builds the graph exactly like main.py's _build_graph (real agents + Postgres
backends), constructs the handler's exact input_state (including
use_rubric_triage=bool(input_path)), streams the node execution to show WHICH
path runs, and prints the final reply.

Usage:
    uv run python scripts/trigger_policy_flow.py <path-to-policy.pdf>
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
from policydecoder.graph.prompt_store import seed_rubrics
from policydecoder.graph.state import AgentContext, GraphContext
from policydecoder.insurer_data import get_insurer_metrics
from policydecoder.logging import configure_logging
from policydecoder.router import heuristic_classify


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

    backends = await create_backends(
        config.database_url,
        embed=Embedder(llm_client=llm, model=config.embeddings_model),
        dims=1536,
        pool_size=config.postgres_pool_size,
    )
    await UserStore(backends.pool).setup()
    await seed_rubrics(backends.store)
    graph = build_graph(agents, checkpointer=backends.checkpointer, store=backends.store)

    user_id = await UserStore(backends.pool).get_or_create("trigger-test@example.com", "file")
    ctx = GraphContext(
        user_id=user_id, contact="trigger-test@example.com", channel="file", agents=agents
    )

    # EXACT handler input_state construction (from handler._handle_graph):
    input_path = pdf_path
    media_urls = [f"file://{pdf_path}"]
    input_state = {
        "contact": "trigger-test@example.com",
        "channel": "file",
        "text": "",
        "media_urls": media_urls,
        "input_path": input_path,
        "case_state": "IDLE",
        "message_count": 0,
        "use_rubric_triage": bool(input_path),
    }

    print(f"input_path={input_path}")
    print(f"use_rubric_triage={input_state['use_rubric_triage']}")
    print("\n=== NODE EXECUTION TRACE (which path runs?) ===")
    nodes_run = []
    async for update in graph.astream(
        input_state,
        {"configurable": {"thread_id": "trigger-flow"}},
        stream_mode="updates",
        context=ctx,
    ):
        for node, data in update.items():
            nodes_run.append(node)
            keys = list(data.keys()) if isinstance(data, dict) else "?"
            print(f"  node={node} writes={keys}")

    print(f"\n=== NODES RUN: {' → '.join(nodes_run)} ===")
    if "triage_page" in nodes_run or "table_analyzer" in nodes_run:
        print(">> RUBRIC TRIAGE PATH CONFIRMED")
    elif "analyst" in nodes_run:
        print(">> LEGACY PATH (extract → analyst)")

    # Get the final reply from the checkpointer
    state = await graph.aget_state({"configurable": {"thread_id": "trigger-flow"}})
    result = state.values if state else {}
    print("\n=== FINAL REPLY ===")
    print(result.get("reply", "(no reply)"))
    print("\n=== STATE SLIM ===")
    print(
        json.dumps(
            {
                k: result.get(k)
                for k in ("document_type", "extraction", "calc_results", "layman_verdict")
                if result.get(k)
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )[:3000]
    )

    await close_backends(backends)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/trigger_policy_flow.py <path-to-policy.pdf>")
        sys.exit(1)
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main(sys.argv[1]))
    finally:
        loop.close()
