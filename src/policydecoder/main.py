"""Entry point for Policy Decoder.

Connects email + Telegram, wires the extractor and analyzer, starts listening.

Usage:
    python -m policydecoder.main
    # or
    policydecoder
"""

import asyncio
import selectors
import threading
from datetime import UTC, datetime
from pathlib import Path

from caspian_sdk import CommClient
from openai import OpenAI

from policydecoder.analyzer import PolicyAnalyzer
from policydecoder.case_manager import case_manager
from policydecoder.config import get_config, validate_langgraph_config
from policydecoder.extractor import PolicyExtractor
from policydecoder.handler import handle
from policydecoder.logging import configure_logging, get_logger

logger = get_logger("policydecoder.main")


class GraphRuntime:
    """Owns the persistent event loop + LangGraph backends.

    The SDK on_message callback is sync and runs in a fresh thread per
    message. With async Postgres backends we must keep one event loop that
    owns the AsyncConnectionPool, so the sync handler submits work via
    asyncio.run_coroutine_threadsafe. Never spin a per-message asyncio.run
    once the pool exists.
    """

    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._backends = None
        self.graph = None
        self.user_store = None
        self.agent_context = None

    def start(self, build_coro):
        """Start the background loop thread and run the startup coroutine on it.

        psycopg async connections require a SelectorEventLoop (they cannot run
        on Windows' default ProactorEventLoop), so we always create the loop
        with the Selector policy.
        """
        loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        self.loop = loop

        def _run():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        self._thread = threading.Thread(target=_run, name="policydecoder-graph-loop", daemon=True)
        self._thread.start()
        future = asyncio.run_coroutine_threadsafe(build_coro(), loop)
        built = future.result(timeout=60)
        # Capture what _build_graph returned — otherwise graph/user_store/
        # agent_context stay None and on_message silently falls back to the
        # legacy supervisor path.
        self.graph = built.get("graph")
        self.user_store = built.get("user_store")
        self.agent_context = built.get("agent_context")
        self._backends = built.get("backends")

    def stop(self):
        """Cancel pending tasks, close backends, stop the loop."""
        loop = self.loop
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._shutdown(), loop).result(timeout=15)
        except Exception as e:
            logger.warning("GraphRuntime shutdown error: %s", e)

    async def _shutdown(self):
        from policydecoder.graph.backends import close_backends

        loop = self.loop
        if self._backends is not None:
            await close_backends(self._backends)
        # Cancel remaining tasks
        if loop is not None:
            for task in asyncio.all_tasks(loop):
                task.cancel()
            loop.stop()


async def _build_graph(config, llm, extractor, analyzer):
    """Construct agents, backends, UserStore, and the compiled graph."""
    from policydecoder.agents.extractor_agent import ExtractorAgent
    from policydecoder.agents.health_analyst import HealthAnalyst
    from policydecoder.agents.letter_drafter import LetterDrafter
    from policydecoder.agents.life_analyst import LifeAnalyst
    from policydecoder.agents.researcher_agent import ResearcherAgent
    from policydecoder.docling_parser import parse_document
    from policydecoder.embeddings import Embedder
    from policydecoder.graph.backends import create_backends
    from policydecoder.graph.identity import UserStore
    from policydecoder.graph.pipeline import build_graph
    from policydecoder.graph.state import AgentContext
    from policydecoder.insurer_data import get_insurer_metrics
    from policydecoder.router import classify_document, heuristic_classify

    async def _router_run(media_urls, input_path=None):
        if input_path:
            parsed = parse_document(Path(input_path))
            if parsed:
                label = heuristic_classify(parsed["markdown"])
                if label in ("HEALTH", "LIFE", "TERM"):
                    return label, 0.5
            return "LIFE", 0.0
        label, confidence = classify_document(
            llm, media_urls, model=config.vision_model, fallback_text=""
        )
        return label, confidence

    class RouterAgent:
        async def run(self, media_urls, input_path=None):
            return await _router_run(media_urls, input_path)

    # Specialist agents — shared between the graph and the legacy supervisor.
    router = RouterAgent()
    extractor_agent = ExtractorAgent(extractor=extractor, llm_client=llm)
    researcher = ResearcherAgent(llm_client=llm)
    health_analyst = HealthAnalyst(
        llm_client=llm,
        analyzer=analyzer,
        benchmark_lookup=get_insurer_metrics,
    )
    life_analyst = LifeAnalyst(llm_client=llm, analyzer=analyzer)
    letter_drafter = LetterDrafter(llm_client=llm, analyzer=analyzer)

    agent_context = AgentContext(
        router=router,
        extractor_agent=extractor_agent,
        researcher=researcher,
        health_analyst=health_analyst,
        life_analyst=life_analyst,
        letter_drafter=letter_drafter,
        analyzer=analyzer,
        llm=llm,
    )

    embedder = Embedder(llm_client=llm, model=config.embeddings_model)
    backends = None
    checkpointer = store = None
    if config.langgraph_enabled:
        backends = await create_backends(
            config.database_url,
            embed=embedder,
            dims=1536,
            pool_size=config.postgres_pool_size,
        )
        checkpointer = backends.checkpointer
        store = backends.store

    user_store = UserStore(backends.pool) if backends else None
    if user_store is not None:
        await user_store.setup()

    # Seed per-product rubrics into the store (idempotent upsert by version).
    if store is not None:
        from policydecoder.graph.prompt_store import seed_rubrics

        await seed_rubrics(store)
        logger.info("  Rubrics: seeded into store")

    graph = build_graph(agent_context, checkpointer=checkpointer, store=store)
    logger.info("  Graph nodes: %s", ", ".join(sorted(graph.get_graph().nodes.keys())))

    return {
        "agent_context": agent_context,
        "backends": backends,
        "user_store": user_store,
        "graph": graph,
    }


def run() -> None:
    configure_logging()
    config = get_config()
    validate_langgraph_config(config)

    client = CommClient(
        api_key=config.caspian_api_key,
        base_url=config.caspian_base_url,
    )

    email_conn = client.connect_email(username=config.agent_username)
    telegram_conn = client.connect_telegram(bot_token=config.telegram_bot_token)

    logger.info("Policy Decoder ONLINE")
    logger.info("  Email:    %s", email_conn["address"])
    logger.info("  Telegram: @%s", telegram_conn["address"])
    logger.info("  LLM:      %s", config.llm_model)
    logger.info("  Vision:   %s", config.vision_model)
    logger.info("  Started:  %sZ", datetime.now(UTC).isoformat()[:19])
    logger.info("  Guardrails: %s", "enabled" if config.guardrails_enabled else "off")
    logger.info("  Opik:     %s", "enabled" if config.opik_enabled else "off")
    logger.info("  LangGraph: %s", "enabled" if config.langgraph_enabled else "off")

    llm = OpenAI(
        api_key=config.openai_api_key,
        base_url=config.openai_base_url,
    )
    extractor = PolicyExtractor(llm)
    analyzer = PolicyAnalyzer(llm)

    # Build the multi-agent pipeline (supervisor + specialists).
    from policydecoder.agents.extractor_agent import ExtractorAgent
    from policydecoder.agents.health_analyst import HealthAnalyst
    from policydecoder.agents.letter_drafter import LetterDrafter
    from policydecoder.agents.life_analyst import LifeAnalyst
    from policydecoder.agents.researcher_agent import ResearcherAgent
    from policydecoder.insurer_data import get_insurer_metrics
    from policydecoder.router import classify_document
    from policydecoder.supervisor import Supervisor

    async def _router_run(media_urls, input_path=None):
        if input_path:
            from policydecoder.docling_parser import parse_document
            from policydecoder.router import heuristic_classify

            parsed = parse_document(Path(input_path))
            if parsed:
                label = heuristic_classify(parsed["markdown"])
                if label in ("HEALTH", "LIFE", "TERM"):
                    return label, 0.5
            return "LIFE", 0.0
        label, confidence = classify_document(
            llm, media_urls, model=config.vision_model, fallback_text=""
        )
        return label, confidence

    class RouterAgent:
        async def run(self, media_urls, input_path=None):
            return await _router_run(media_urls, input_path)

    supervisor = Supervisor(
        router=RouterAgent(),
        extractor=ExtractorAgent(extractor=extractor, llm_client=llm),
        researcher=ResearcherAgent(llm_client=llm),
        health_analyst=HealthAnalyst(
            llm_client=llm,
            analyzer=analyzer,
            benchmark_lookup=get_insurer_metrics,
        ),
        life_analyst=LifeAnalyst(llm_client=llm, analyzer=analyzer),
        letter_drafter=LetterDrafter(llm_client=llm, analyzer=analyzer),
    )

    # LangGraph path: persistent loop + backends + graph (when enabled).
    graph_runtime = None
    if config.langgraph_enabled:
        graph_runtime = GraphRuntime()
        graph_runtime.start(lambda: _build_graph(config, llm, extractor, analyzer))
        graph = graph_runtime.graph
        user_store = graph_runtime.user_store
        agent_context = graph_runtime.agent_context
        logger.info("  LangGraph: graph compiled, backends ready")
    else:
        graph = None
        user_store = None
        agent_context = None
        from policydecoder.store import Persistence

        store = Persistence()
        case_manager.load_all_from(store)
        logger.info("  Persistence: %s", store.db_path)

    @client.on_message
    def on_message(message):
        if config.langgraph_enabled and graph is not None:
            handle(
                client,
                message,
                extractor,
                analyzer,
                supervisor=None,
                graph=graph,
                graph_runtime=graph_runtime,
                user_store=user_store,
                agent_context=agent_context,
            )
        else:
            handle(client, message, extractor, analyzer, supervisor=supervisor)

    try:
        client.listen(ack="Policy Decoder is analyzing your message...")
    finally:
        if graph_runtime is not None:
            graph_runtime.stop()


if __name__ == "__main__":
    run()
