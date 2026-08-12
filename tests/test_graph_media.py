"""Tests for the LangGraph media pipeline (route → extract ∥ research → analyst)."""

import pytest

from tests.graph_fakes import FakeExtractor, FakeRouter, make_agents, make_context, make_graph


@pytest.mark.asyncio
async def test_media_life_full_flow():
    """Media → route(LIFE) → extract+research → life analyst → formatted report."""
    graph = make_graph()
    result = await graph.ainvoke(
        {
            "contact": "a@b.c",
            "channel": "email",
            "media_urls": ["file:///tmp/x.pdf"],
            "input_path": "/tmp/x.pdf",
            "text": "",
            "case_state": "IDLE",
        },
        {"configurable": {"thread_id": "t1"}},
        context=make_context(),
    )
    assert "honest take" in result["reply"]
    assert result["analysis"]["is_likely_missold"] is True
    assert result["calc_results"]["xirr"] > 0  # deterministic math ran


@pytest.mark.asyncio
async def test_media_health_flow():
    """Media → route(HEALTH) → health analyst path."""
    agents = make_agents(router=FakeRouter(label="HEALTH"))
    graph = make_graph(agents)
    result = await graph.ainvoke(
        {
            "contact": "a@b.c",
            "channel": "email",
            "media_urls": ["file:///tmp/x.jpg"],
            "text": "",
            "case_state": "IDLE",
        },
        {"configurable": {"thread_id": "t2"}},
        context=make_context(agents=agents),
    )
    assert result["analysis"]["verdict"] == "GOOD"


@pytest.mark.asyncio
async def test_media_short_circuit_reply():
    """Extractor short-circuits → fixed 'partial document' reply, no analyst."""
    agents = make_agents(extractor_agent=FakeExtractor(short_circuited=True))
    graph = make_graph(agents)
    result = await graph.ainvoke(
        {
            "contact": "a@b.c",
            "channel": "email",
            "media_urls": ["file:///tmp/x.pdf"],
            "input_path": "/tmp/x.pdf",
            "text": "",
            "case_state": "IDLE",
        },
        {"configurable": {"thread_id": "t3"}},
        context=make_context(agents=agents),
    )
    assert "full policy document" in result["reply"]
    assert "analysis" not in result
