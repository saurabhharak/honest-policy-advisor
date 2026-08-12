"""Tests for graph state helpers + routing functions."""

from policydecoder.graph.nodes import after_extract, case_summary, route_intent, route_start
from policydecoder.graph.state import AgentContext, GraphContext, PipelineState


def test_route_start_media_vs_text():
    assert route_start({"media_urls": ["u"], "input_path": None}) == {"route": "media_route"}
    assert route_start({"media_urls": [], "input_path": "/tmp/x.pdf"}) == {"route": "media_route"}
    assert route_start({"media_urls": [], "input_path": None}) == {"route": "text_intent"}


def test_after_extract_short_circuit():
    assert after_extract({"short_circuited": True}) == "format_short_circuit"
    assert after_extract({"short_circuited": False}) == "analyst"


def test_route_intent_dispatch():
    assert route_intent({"intent": "STATUS_CHECK"}) == "status_reply"
    assert route_intent({"intent": "CONFIRM_ACTION"}) == "confirm_action"
    assert route_intent({"intent": "NEW_POLICY"}) == "text_answer"
    assert route_intent({"intent": "UNKNOWN"}) == "text_answer"


def test_case_summary_shape():
    summary = case_summary(
        {
            "case_state": "ANALYZED",
            "policy_data": {"policy_name": "X"},
            "analysis": {"is_likely_missold": True},
        }
    )
    assert '"policy": "X"' in summary
    assert '"missold": true' in summary


def test_context_dataclasses():
    ctx = GraphContext(user_id="u", contact="c", channel="email", agents=None)
    assert ctx.user_id == "u"
    assert ctx.agents is None

    class _A:
        pass

    ac = AgentContext(
        router=_A(),
        extractor_agent=_A(),
        researcher=_A(),
        health_analyst=_A(),
        life_analyst=_A(),
        letter_drafter=_A(),
        analyzer=_A(),
        llm=None,
    )
    assert ac.router is not None


def test_state_keys_exist():
    """PipelineState supports the keys the nodes read."""
    state: PipelineState = {
        "route": "media_route",
        "text": "hi",
        "media_urls": [],
        "input_path": None,
        "document_type": "LIFE",
        "extraction": {},
        "analysis": {},
        "reply": "ok",
    }
    assert state["route"] == "media_route"
