"""Shared fakes for the LangGraph pipeline tests. No real LLM/channels/timers."""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from policydecoder.graph.pipeline import build_graph
from policydecoder.graph.state import AgentContext, GraphContext


class FakeLLM:
    """Mimic the OpenAI client shape (llm.chat.completions.create) for memory calls."""

    class _Completions:
        def __init__(self, fake_llm):
            self._fake = fake_llm

        def create(self, model, messages, temperature=0.7, max_tokens=2000, timeout=15):
            # The memory extractor prompt expects {"facts": [...]}; the profile
            # merge prompt expects {"profile": {...}}. Return the right shape.
            user = messages[-1]["content"] if messages else ""
            if "profile" in user:
                payload = '{"profile": {"age": 35, "family": null, "policies": [], "preferences": [], "events": []}}'
            else:
                payload = '{"facts": ["user is 35 years old"]}'

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
        self.model = "gpt-4o-mini"


class FakeRouter:
    def __init__(self, label="LIFE"):
        self.label = label

    async def run(self, media_urls, input_path=None):
        return self.label, 0.9


class FakeExtractor:
    def __init__(self, data=None, short_circuited=False):
        self.data = data or {
            "policy_name": "Test Policy",
            "annual_premium": 50000,
            "policy_term_years": 20,
            "sum_assured": 1000000,
            "maturity_value_at_8pct": 2000000,
        }
        self.short_circuited = short_circuited

    async def run(self, media_urls, document_type="LIFE", input_path=None):
        return {
            "data": self.data,
            "missing": [],
            "short_circuited": self.short_circuited,
        }


class FakeResearcher:
    async def run(self, topic):
        return [{"source": "https://joinditto.in/a", "claim": "c", "url": "u"}]


class FakeLifeAnalyst:
    async def run(self, extraction, calc_results, findings):
        return {
            "is_likely_missold": True,
            "misselling_reasons": ["x"],
            "recommended_action": "complaint_only",
            "summary": "test summary",
            "key_findings": ["k"],
        }


class FakeHealthAnalyst:
    async def run(self, extraction, findings):
        return {"verdict": "GOOD", "summary": "fine", "red_flags": []}


class FakeDrafter:
    async def run(self, letter_type, policy_data, analysis):
        return f"drafted {letter_type} letter"


class FakeAnalyzer:
    def classify_intent(self, message_text, case_state, case_summary):
        if "status" in message_text.lower():
            return {"intent": "STATUS_CHECK", "confidence": 0.95, "extracted_info": {}}
        if "confirm" in message_text.lower() or "yes" in message_text.lower():
            return {"intent": "CONFIRM_ACTION", "confidence": 0.9, "extracted_info": {}}
        if message_text.strip().isdigit():
            return {
                "intent": "INFO_RESPONSE",
                "confidence": 0.9,
                "extracted_info": {"user_age": message_text.strip()},
            }
        return {"intent": "NEW_POLICY", "confidence": 0.8, "extracted_info": {}}


def make_agents(**overrides):
    """Build an AgentContext with fakes; override individual agents as needed."""
    defaults = dict(
        router=FakeRouter(),
        extractor_agent=FakeExtractor(),
        researcher=FakeResearcher(),
        health_analyst=FakeHealthAnalyst(),
        life_analyst=FakeLifeAnalyst(),
        letter_drafter=FakeDrafter(),
        analyzer=FakeAnalyzer(),
        llm=FakeLLM(),
    )
    defaults.update(overrides)
    return AgentContext(**defaults)


def make_graph(agents=None, store=None, checkpointer=None):
    """Build a compiled graph with in-memory backends + a stub embedder."""
    agents = agents or make_agents()

    def embed(texts):
        return [[0.0] * 1536 for _ in texts]

    checkpointer = checkpointer or InMemorySaver()
    store = store or InMemoryStore(index={"embed": embed, "dims": 1536})
    return build_graph(agents, checkpointer=checkpointer, store=store)


def make_context(user_id="u1", contact="a@b.c", channel="email", agents=None):
    return GraphContext(
        user_id=user_id,
        contact=contact,
        channel=channel,
        agents=agents or make_agents(),
    )
