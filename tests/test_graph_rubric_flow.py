"""Full multi-page rubric flow: media → split → dual-track triage → accumulate
→ deterministic calc → layman writer → formatted reply, with fake agents.
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from policydecoder.graph.pipeline import build_graph
from policydecoder.graph.state import AgentContext, GraphContext


class FakeLLM:
    """Responds appropriately to each prompt type by looking at the content."""

    class _Completions:
        def __init__(self, fake_llm):
            self._fake = fake_llm

        def create(self, model, messages, temperature=0.7, max_tokens=2000, timeout=15):
            user = messages[-1]["content"] if messages else ""
            if "page reviewer" in user and "PAGE 2 OF" not in user and "PAGE 3 OF" not in user:
                payload = '{"page_number": 1, "fields": {"policy_name": "Optima Secure"}, "findings": [], "page_summary": "policy page"}'
            elif "table reviewer" in user:
                payload = '{"fields": {"sum_insured": 1500000, "annual_premium": 34526}, "findings": [], "table_summary": "tables"}'
            elif "plain-language" in user:
                payload = '{"summary": "This is a solid policy.", "items": [{"severity": "info", "what": "No co-pay", "why_it_matters": "you pay nothing extra", "what_to_do": "nothing"}], "verdict": "GOOD"}'
            else:
                payload = (
                    '{"page_number": 1, "fields": {}, "findings": [], "page_summary": "other"}'
                )

            class _Msg:
                content = payload

            class _Choice:
                message = _Msg()

            class _Resp:
                choices = [_Choice()]

            return _Resp()

    class _Chat:
        def __init__(self, fake_llm):
            self.completions = FakeLLM._Completions(fake_llm)

    def __init__(self):
        self.chat = self._Chat(self)
        self.model = "deepseek-ai/DeepSeek-V4-Flash"


class FakeRouter:
    async def run(self, media_urls, input_path=None):
        return "HEALTH", 0.9


class _NullAgent:
    async def run(self, **kwargs):
        return {}


def _make_agents():
    return AgentContext(
        router=FakeRouter(),
        extractor_agent=_NullAgent(),
        researcher=_NullAgent(),
        health_analyst=_NullAgent(),
        life_analyst=_NullAgent(),
        letter_drafter=_NullAgent(),
        analyzer=None,
        llm=FakeLLM(),
    )


def _make_graph(agents):
    """Build a graph with in-memory backends."""

    def embed(texts):
        return [[0.0] * 1536 for _ in texts]

    store = InMemoryStore(index={"embed": embed, "dims": 1536})
    checkpointer = InMemorySaver()
    graph = build_graph(agents, checkpointer=checkpointer, store=store)
    return graph, store


@pytest.mark.asyncio
async def test_full_multi_page_rubric_flow():
    agents = _make_agents()
    seed_pages = [
        "## Optima Secure\nPolicy name and welcome text.",
        "## Premium\nAnnual premium table.",
        "## Terms\nSum insured and coverage terms.",
    ]
    graph, store = _make_graph(agents)
    ctx = GraphContext(user_id="u1", contact="a@b.c", channel="email", agents=agents)

    result = await graph.ainvoke(
        {
            "contact": "a@b.c",
            "channel": "email",
            "media_urls": ["file:///tmp/x.pdf"],
            "input_path": "/tmp/x.pdf",
            "text": "",
            "case_state": "IDLE",
            "use_rubric_triage": True,
            "pages_markdown": seed_pages,  # injected so split_pages keeps it
            "page_count": len(seed_pages),
            "tables_json": [],
        },
        {"configurable": {"thread_id": "t1"}},
        context=ctx,
    )

    assert result["reply"]
    assert "honest take" in result["reply"]
    # The layman verdict made it into the reply
    assert "solid policy" in result["reply"] or "What to know" in result["reply"]
    # Calc ran deterministically (health path → overall)
    assert result["calc_results"]["overall"] in ("GOOD", "REVIEW", "ALERT")
    # Memory L0 written (raw event appended)
    items = await store.asearch(("u1", "l0"))
    assert len(items) >= 1


@pytest.mark.asyncio
async def test_missing_required_triggers_targeted_re_read():
    """If required fields are missing after accumulate, targeted_re_read runs
    (never a full-doc re-read) and the graph still completes."""

    class MissingLLM(FakeLLM):
        class _Completions:
            def __init__(self, fake):
                self._fake = fake
                self.calls = 0

            def create(self, model, messages, temperature=0.7, max_tokens=2000, timeout=15):
                user = messages[-1]["content"] if messages else ""
                if "table reviewer" in user:
                    payload = '{"fields": {}, "findings": [], "table_summary": ""}'
                elif "plain-language" in user:
                    payload = '{"summary": "ok", "items": [], "verdict": "REVIEW"}'
                else:
                    # page reviewer calls: first pass (page triage) returns nothing
                    # (missing required); the targeted re-read pass returns the premium.
                    self.calls += 1
                    if self.calls >= 2:
                        payload = '{"page_number": 2, "fields": {"annual_premium": 34526, "sum_insured": 1500000}, "findings": [], "page_summary": "premium page"}'
                    else:
                        payload = '{"page_number": 1, "fields": {}, "findings": [], "page_summary": "welcome"}'

                class _Msg:
                    content = payload

                class _Choice:
                    message = _Msg()

                class _Resp:
                    choices = [_Choice()]

                return _Resp()

        def __init__(self):
            super().__init__()
            self.chat = FakeLLM._Chat(self)
            self.chat.completions = self._Completions(self)

    agents = _make_agents()
    # replace the llm so we control responses
    from tests.graph_fakes import FakeRouter

    agents.llm = MissingLLM()
    agents.router = FakeRouter(label="HEALTH")

    seed_pages = ["page1 welcome", "page2 premium 34526", "page3 terms"]
    graph, store = _make_graph(agents)
    ctx = GraphContext(user_id="u1", contact="a@b.c", channel="email", agents=agents)

    result = await graph.ainvoke(
        {
            "contact": "a@b.c",
            "channel": "email",
            "media_urls": ["file:///tmp/x.pdf"],
            "input_path": "/tmp/x.pdf",
            "text": "",
            "case_state": "IDLE",
            "use_rubric_triage": True,
            "pages_markdown": seed_pages,
            "page_count": len(seed_pages),
            "tables_json": [],
        },
        {"configurable": {"thread_id": "t2"}},
        context=ctx,
    )
    assert result["reply"]
    assert result["extraction"]["annual_premium"] == 34526  # recovered by targeted re-read
