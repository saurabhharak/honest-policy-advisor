"""Sync task wrappers for Opik's ThreadPoolExecutor evaluate().

Opik calls the task synchronously in worker threads. Our agents are
async, so each task creates a FRESH event loop inside the worker thread
(never reuses a loop created on another thread) and closes it in
finally. Agent instances are built inside the task so any clients they
create (OpenAI, httpx) belong to that loop.

The extractor task additionally patches parse_document to serve a
pre-parsed Docling result from the eval cache, so the metric loop never
re-runs Docling/OCR.
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any
from unittest.mock import patch

from policydecoder.agents.extractor_agent import ExtractorAgent
from policydecoder.agents.health_analyst import HealthAnalyst
from policydecoder.agents.letter_drafter import LetterDrafter
from policydecoder.agents.life_analyst import LifeAnalyst
from policydecoder.agents.researcher_agent import ResearcherAgent
from policydecoder.analyzer import PolicyAnalyzer
from policydecoder.evals.data import load_docling_cache
from policydecoder.extractor import PolicyExtractor
from policydecoder.insurer_data import get_insurer_metrics

AgentRunner = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


def make_sync_task(async_agent_runner: AgentRunner) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Wrap an async agent run for Opik's sync ThreadPoolExecutor.

    Creates a brand-new event loop per call to avoid 'Event loop is
    closed' / 'Task attached to a different loop' when agents build
    clients inside the loop.
    """

    def sync_task(item: dict[str, Any]) -> dict[str, Any]:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            output = loop.run_until_complete(async_agent_runner(item.get("inputs", {})))
        finally:
            loop.close()
        return {"output": output, **item.get("echo", {})}

    return sync_task


def _run_async_in_fresh_loop(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine to completion in a fresh loop (blocking)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Agent runner builders — each builds the agent INSIDE the task so clients
# (OpenAI/httpx) are created on the task's own event loop.
# ---------------------------------------------------------------------------


def router_task(
    llm_client: Any, vision_model: str | None = None
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    from policydecoder.config import get_config

    if vision_model is None:
        vision_model = get_config().vision_model

    def _build_and_run(inputs: dict[str, Any]) -> dict[str, Any]:
        import asyncio

        from policydecoder.evals.data import load_docling_cache
        from policydecoder.router import classify_document, heuristic_classify

        async def _run() -> dict[str, Any]:
            input_path = inputs.get("input_path")
            if input_path:
                cached = load_docling_cache(input_path)
                if cached is not None:
                    label = heuristic_classify(cached["markdown"])
                    if label in ("HEALTH", "LIFE"):
                        return {"label": label, "confidence": 0.5}
            label, confidence = classify_document(
                llm_client,
                inputs.get("media_urls") or [],
                model=vision_model,
                fallback_text=inputs.get("fallback_text", ""),
            )
            return {"label": label, "confidence": confidence}

        return asyncio.run(_run())

    def _task(item: dict[str, Any]) -> dict[str, Any]:
        out = _build_and_run(item.get("inputs", {}))
        # Echo gold + a top-level label string so Equals can compare
        # output against reference directly.
        return {
            "output": out["label"],
            "label": out["label"],
            "confidence": out["confidence"],
            **item.get("echo", {}),
            "reference": item.get("expected_label"),
        }

    return _task


def extractor_task(llm_client: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _build_and_run(inputs: dict[str, Any]) -> dict[str, Any]:
        # Build the agent inside this task (clients bound to this loop).
        agent = ExtractorAgent(extractor=PolicyExtractor(llm_client), llm_client=llm_client)
        input_path = inputs.get("input_path")
        cached = load_docling_cache(input_path) if input_path else None
        if cached is not None:
            # The agent imports parse_document into its own module namespace.
            with patch("policydecoder.agents.extractor_agent.parse_document", return_value=cached):
                return _run_async_in_fresh_loop(
                    agent.run(
                        media_urls=inputs.get("media_urls", []),
                        document_type=inputs.get("document_type", "HEALTH"),
                        input_path=input_path,
                    )
                )
        return _run_async_in_fresh_loop(
            agent.run(
                media_urls=inputs.get("media_urls", []),
                document_type=inputs.get("document_type", "HEALTH"),
                input_path=input_path,
            )
        )

    def _task(item: dict[str, Any]) -> dict[str, Any]:
        out = _build_and_run(item.get("inputs", {}))
        # Echo gold so metrics can compare against the reference dict.
        return {
            "output": out,
            **item.get("echo", {}),
            "reference": item.get("reference"),
            "short_circuited": out.get("short_circuited"),
            "gold_short_circuited": item.get("short_circuited"),
        }

    return _task


def researcher_task(llm_client: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _build_and_run(inputs: dict[str, Any]) -> dict[str, Any]:
        agent = ResearcherAgent(llm_client=llm_client)
        return _run_async_in_fresh_loop(agent.run(topic=inputs.get("topic", "")))

    return lambda item: {"output": _build_and_run(item.get("inputs", {})), **item.get("echo", {})}


def health_analyst_task(llm_client: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _build_and_run(inputs: dict[str, Any]) -> dict[str, Any]:
        agent = HealthAnalyst(
            llm_client=llm_client,
            analyzer=PolicyAnalyzer(llm_client),
            benchmark_lookup=get_insurer_metrics,
        )
        return _run_async_in_fresh_loop(
            agent.run(
                extraction=inputs.get("extraction", {}),
                findings=inputs.get("findings", []),
            )
        )

    def _task(item: dict[str, Any]) -> dict[str, Any]:
        analysis = _build_and_run(item.get("inputs", {}))
        # Echo gold so Equals can compare the verdict.
        return {
            "output": analysis.get("verdict"),
            "verdict": analysis.get("verdict"),
            **item.get("echo", {}),
            "reference": item.get("expected_verdict"),
        }

    return _task


def life_analyst_task(llm_client: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _build_and_run(inputs: dict[str, Any]) -> dict[str, Any]:
        agent = LifeAnalyst(
            llm_client=llm_client,
            analyzer=PolicyAnalyzer(llm_client),
        )
        extraction = inputs.get("extraction", {})
        calc = inputs.get("calc_results", {})
        analysis = _run_async_in_fresh_loop(
            agent.run(
                extraction=extraction,
                calc_results=calc,
                findings=inputs.get("findings", []),
            )
        )
        return {"analysis": analysis, "calc_results": calc}

    def _task(item: dict[str, Any]) -> dict[str, Any]:
        out = _build_and_run(item.get("inputs", {}))
        # Echo gold so Equals can compare is_likely_missold.
        return {
            "output": out["analysis"].get("is_likely_missold"),
            "calc_results": out["calc_results"],
            **item.get("echo", {}),
            "reference": item.get("expected_missold"),
        }

    return _task


def letter_drafter_task(llm_client: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _build_and_run(inputs: dict[str, Any]) -> dict[str, Any]:
        agent = LetterDrafter(
            llm_client=llm_client,
            analyzer=PolicyAnalyzer(llm_client),
        )
        return _run_async_in_fresh_loop(
            agent.run(
                letter_type=inputs.get("letter_type", "complaint"),
                policy_data=inputs.get("policy_data", {}),
                analysis=inputs.get("analysis", {}),
            )
        )

    def _task(item: dict[str, Any]) -> dict[str, Any]:
        letter = _build_and_run(item.get("inputs", {}))
        # Echo the joined gold phrases so Contains can verify each.
        return {
            "output": letter,
            **item.get("echo", {}),
            "reference": "\n".join(item.get("must_contain", [])),
        }

    return _task


# Map agent name → task builder.
TASK_BUILDERS = {
    "router": router_task,
    "extractor": extractor_task,
    "researcher": researcher_task,
    "health_analyst": health_analyst_task,
    "life_analyst": life_analyst_task,
    "letter_drafter": letter_drafter_task,
}
