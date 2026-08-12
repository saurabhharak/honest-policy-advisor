"""Graph state schema and runtime context for the LangGraph pipeline."""

from dataclasses import dataclass
from typing import Any, TypedDict


class PipelineState(TypedDict, total=False):
    """Thread-scoped state flowing through the policy-decoder graph."""

    # message / channel inputs
    contact: str
    channel: str
    media_urls: list[str]
    input_path: str | None
    text: str
    route: str  # set by route_start: "media_route" | "text_intent"
    use_rubric_triage: bool  # opt-in: route media through the rubric dual-track path

    # media pipeline
    document_type: str  # HEALTH | LIFE
    extraction: dict[str, Any]
    missing: list[str]
    short_circuited: bool
    findings: list[dict[str, Any]]
    calc_results: dict[str, Any]
    analysis: dict[str, Any]
    letter_type: str | None
    letter: str

    # rubric / page-triage (dual-track)
    rubric: dict[str, Any]  # loaded once by prepare_triage into state
    pages_markdown: list[str]  # per-page markdown from Docling
    page_count: int
    tables_json: list[Any]  # full tables JSON (Docling/TableFormer, cross-page)
    page_outputs: list[dict[str, Any]]  # Track A per-page triage results
    table_output: dict[str, Any] | None  # Track B table-analyzer result
    layman_verdict: dict[str, Any]  # final plain-language verdict

    # text flow (replaces Case fields)
    intent: str
    intent_confidence: float
    case_state: str  # mirrors CaseState values for prompt continuity
    policy_data: dict[str, Any]
    actions_completed: list[dict[str, Any]]
    pending_actions: list[dict[str, Any]]
    user_age: int | None
    message_count: int

    # outputs
    reply: str

    # memory
    memory_context: str  # assembled from L1-L3, injected into prompts
    new_atoms: list[str]  # written by extract_l1, consumed by merge_l3


@dataclass
class AgentContext:
    """The agent graph dependencies injected per run.

    Holds the specialist agents + analyzer + llm so graph nodes can reach
    them through runtime.context (LangGraph's "run dependencies").
    """

    router: Any
    extractor_agent: Any
    researcher: Any
    health_analyst: Any
    life_analyst: Any
    letter_drafter: Any
    analyzer: Any
    llm: Any = None


@dataclass
class GraphContext:
    """Per-invocation context injected via Runtime (context_schema)."""

    user_id: str
    contact: str
    channel: str
    agents: AgentContext | None = None
