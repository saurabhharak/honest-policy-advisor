"""Tests for L0-L3 memory: writes, gating, ordering, and cross-session recall."""

import pytest

from tests.graph_fakes import FakeLLM, make_agents, make_context, make_graph


@pytest.mark.asyncio
async def test_l0_written_every_turn():
    """L0 raw docs are appended per thread (no LLM needed)."""
    graph = make_graph()
    ctx = make_context()
    await graph.ainvoke(
        {"contact": "a@b.c", "channel": "email", "text": "status", "case_state": "IDLE"},
        {"configurable": {"thread_id": "t1"}},
        context=ctx,
    )
    store = graph.store
    items = await store.asearch(("u1", "l0"))
    assert len(items) == 1


@pytest.mark.asyncio
async def test_l1_l3_not_written_on_trivial_turn():
    """Chit-chat (no analysis, no age) → no L1 atoms, no L3 profile."""

    class TrivialLLM(FakeLLM):
        pass

    class TrivialAnalyzer:
        def classify_intent(self, message_text, case_state, case_summary):
            return {"intent": "QUESTION", "confidence": 0.9, "extracted_info": {}}

    agents = make_agents(llm=TrivialLLM(), analyzer=TrivialAnalyzer())
    graph = make_graph(agents)
    ctx = make_context(agents=agents)
    await graph.ainvoke(
        {"contact": "a@b.c", "channel": "email", "text": "hi", "case_state": "IDLE"},
        {"configurable": {"thread_id": "t1"}},
        context=ctx,
    )
    store = graph.store
    assert await store.asearch(("u1", "l1", "atoms")) == []
    assert await store.aget(("u1", "l3", "profile"), "profile") is None


@pytest.mark.asyncio
async def test_l1_atoms_upsert_by_hash_and_l3_merge():
    """Completed analysis → L1 atoms extracted + deduped, L3 profile merged.

    The FakeLLM returns the same fact every time, so running twice must
    produce exactly ONE atom (hash upsert) and the profile exists.
    """
    graph = make_graph()
    ctx = make_context()
    for i in range(2):
        await graph.ainvoke(
            {
                "contact": "a@b.c",
                "channel": "email",
                "media_urls": ["file:///tmp/x.pdf"],
                "input_path": "/tmp/x.pdf",
                "text": "",
                "case_state": "IDLE",
            },
            {"configurable": {"thread_id": f"t{i}"}},
            context=ctx,
        )
    store = graph.store
    atoms = await store.asearch(("u1", "l1", "atoms"))
    assert len(atoms) == 1  # deduped by content hash

    profile = await store.aget(("u1", "l3", "profile"), "profile")
    assert profile is not None
    assert "profile" in profile.value


@pytest.mark.asyncio
async def test_memory_load_cross_thread_recall():
    """memory_load surfaces stored L1/L3 across a different thread for the same user."""
    graph = make_graph()
    ctx = make_context()
    # Thread 1: media analysis → writes L1 atom + L3 profile.
    await graph.ainvoke(
        {
            "contact": "a@b.c",
            "channel": "email",
            "media_urls": ["file:///tmp/x.pdf"],
            "input_path": "/tmp/x.pdf",
            "text": "",
            "case_state": "IDLE",
        },
        {"configurable": {"thread_id": "t1"}},
        context=ctx,
    )
    # Thread 2: a text turn should load memory_context from the store.
    result = await graph.ainvoke(
        {"contact": "a@b.c", "channel": "email", "text": "status", "case_state": "IDLE"},
        {"configurable": {"thread_id": "t2"}},
        context=ctx,
    )
    assert "reply" in result


@pytest.mark.asyncio
async def test_merge_l3_gated_on_new_atoms():
    """merge_l3 only runs when extract_l1 produced ≥1 new atom.

    If the store already has the atom (no new_atoms), the L3 profile is
    NOT re-written on the second turn.
    """
    graph = make_graph()
    ctx = make_context()
    await graph.ainvoke(
        {
            "contact": "a@b.c",
            "channel": "email",
            "media_urls": ["file:///tmp/x.pdf"],
            "input_path": "/tmp/x.pdf",
            "text": "",
            "case_state": "IDLE",
        },
        {"configurable": {"thread_id": "t1"}},
        context=ctx,
    )
    store = graph.store
    profile_after_first = await store.aget(("u1", "l3", "profile"), "profile")
    first_ts = profile_after_first.value["ts"]

    # Second turn: the atom already exists → no new_atoms → merge_l3 skipped.
    await graph.ainvoke(
        {
            "contact": "a@b.c",
            "channel": "email",
            "media_urls": ["file:///tmp/x.pdf"],
            "input_path": "/tmp/x.pdf",
            "text": "",
            "case_state": "IDLE",
        },
        {"configurable": {"thread_id": "t2"}},
        context=ctx,
    )
    profile_after_second = await store.aget(("u1", "l3", "profile"), "profile")
    assert profile_after_second.value["ts"] == first_ts  # not rewritten


@pytest.mark.asyncio
async def test_l2_scenario_written_after_analysis():
    """update_l2 writes a per-policy scenario after a completed analysis."""
    graph = make_graph()
    ctx = make_context()
    await graph.ainvoke(
        {
            "contact": "a@b.c",
            "channel": "email",
            "media_urls": ["file:///tmp/x.pdf"],
            "input_path": "/tmp/x.pdf",
            "text": "",
            "case_state": "IDLE",
        },
        {"configurable": {"thread_id": "t1"}},
        context=ctx,
    )
    store = graph.store
    scenarios = await store.asearch(("u1", "l2", "scenarios"))
    assert len(scenarios) == 1
    assert scenarios[0].value["policy_name"] == "Test Policy"
