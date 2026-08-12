"""Tests for the LangGraph text flow (intent dispatch + memory wiring)."""

import pytest

from tests.graph_fakes import make_agents, make_context, make_graph


@pytest.mark.asyncio
async def test_text_status_reply():
    """A STATUS_CHECK intent routes to status_reply."""
    graph = make_graph()
    result = await graph.ainvoke(
        {"contact": "a@b.c", "channel": "email", "text": "status", "case_state": "IDLE"},
        {"configurable": {"thread_id": "t1"}},
        context=make_context(),
    )
    assert "Case status" in result["reply"]


@pytest.mark.asyncio
async def test_text_confirm_drafts_letter():
    """CONFIRM_ACTION routes to confirm_action → drafts a letter."""
    agents = make_agents()
    graph = make_graph(agents)
    ctx = make_context(agents=agents)
    # Seed a completed analysis + policy data in thread state first.
    result = await graph.ainvoke(
        {
            "contact": "a@b.c",
            "channel": "email",
            "text": "yes",
            "case_state": "ANALYZED",
            "policy_data": {"policy_name": "X", "annual_premium": 50000},
            "analysis": {"recommended_action": "complaint_only"},
        },
        {"configurable": {"thread_id": "t2"}},
        context=ctx,
    )
    assert "letter" in result["reply"]
    assert "drafted" in result["reply"]


@pytest.mark.asyncio
async def test_text_intent_low_confidence_unknown():
    """Low-confidence intent → UNKNOWN → generic answer."""

    class LowConfAnalyzer:
        def classify_intent(self, message_text, case_state, case_summary):
            return {"intent": "STATUS_CHECK", "confidence": 0.3, "extracted_info": {}}

    agents = make_agents(analyzer=LowConfAnalyzer())
    graph = make_graph(agents)
    result = await graph.ainvoke(
        {"contact": "a@b.c", "channel": "email", "text": "hi", "case_state": "IDLE"},
        {"configurable": {"thread_id": "t3"}},
        context=make_context(agents=agents),
    )
    assert result["reply"]  # generic fallback, no crash
