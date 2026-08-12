"""Build the compiled LangGraph for the policy-decoder pipeline.

Graph shape (replaces Supervisor.process_media + the CaseState text machine):

  START → route_start
    media → media_route → (extract ∥ research) → after_extract
              ├─ short_circuited → format_short_circuit
              └─ else → analyst → format_report
    text  → text_intent → route_intent → {text_answer, status_reply, confirm_action}
  every reply path → memory_load → write_l0 → extract_l1 → (conditional) merge_l3
                    → update_l2 → END

Agents are passed at compile time inside GraphContext (runtime context),
so nodes reach them via runtime.context.agents.
"""

from langgraph.graph import END, START, StateGraph

from policydecoder.graph.state import AgentContext, GraphContext, PipelineState
from policydecoder.logging import get_logger

logger = get_logger("policydecoder.graph.pipeline")


def split_pages(state: PipelineState, runtime=None) -> dict:
    """Populate per-page markdown + tables JSON from the Docling parse result.

    If pages_markdown is already in state (e.g. tests or a cached parse), keep
    it. Otherwise parse the local file and pull the per-page markdown + FULL
    tables JSON so the dual-track triage can run. Falls back to a single-page
    document when parsing didn't expose pages_markdown.
    """
    if state.get("pages_markdown"):
        return {}
    from pathlib import Path

    from policydecoder.docling_parser import parse_document

    input_path = state.get("input_path")
    if not input_path:
        return {}
    result = parse_document(Path(input_path))
    if not result:
        return {}
    pages = result.get("pages_markdown") or []
    # Fallback: if per-page split unavailable, treat the whole doc as one page.
    if not pages and result.get("markdown"):
        pages = [result["markdown"]]
    return {
        "pages_markdown": pages,
        "page_count": len(pages) or result.get("page_count", 1),
        "tables_json": result.get("tables_json", []),
    }


def _after_memory(state: PipelineState) -> str:
    """Branch after extract_l1: merge_l3 only when new atoms were produced."""
    if state.get("new_atoms"):
        return "merge_l3"
    return "update_l2"


def build_graph(agents: AgentContext, checkpointer=None, store=None):
    """Compile the pipeline graph.

    agents: AgentContext holding the specialist agents + analyzer + llm.
    checkpointer: LangGraph checkpointer (AsyncPostgresSaver or InMemorySaver).
    store: LangGraph store (AsyncPostgresStore or InMemoryStore) for memory.
    """
    from policydecoder.graph import memory as mem
    from policydecoder.graph import nodes as n
    from policydecoder.graph import triage as tr

    builder = StateGraph(PipelineState, context_schema=GraphContext)

    # Media
    builder.add_node("media_route", n.media_route)
    builder.add_node("extract", n.extract)
    builder.add_node("research", n.research)
    builder.add_node("gate", n.gate)
    builder.add_node("analyst", n.analyst)
    builder.add_node("format_short_circuit", n.format_short_circuit)
    builder.add_node("format_report", n.format_report)

    # Rubric / page-triage (dual-track)
    builder.add_node("split_pages", split_pages)
    builder.add_node("prepare_triage", tr.prepare_triage)
    builder.add_node("triage_page", tr.triage_page)
    builder.add_node("table_analyzer", tr.table_analyzer)
    builder.add_node("accumulate", tr.accumulate)
    builder.add_node("deterministic_calc", tr.deterministic_calc)
    builder.add_node("targeted_re_read", tr.targeted_re_read)
    builder.add_node("layman_writer", tr.layman_writer)
    builder.add_node("format_layman_report", tr.format_layman_report)

    # Text
    builder.add_node("text_intent", n.text_intent)
    builder.add_node("text_answer", n.text_answer)
    builder.add_node("status_reply", n.status_reply)
    builder.add_node("confirm_action", n.confirm_action)

    # Memory
    builder.add_node("memory_load", mem.memory_load)
    builder.add_node("write_l0", mem.write_l0)
    builder.add_node("extract_l1", mem.extract_l1)
    builder.add_node("merge_l3", mem.merge_l3)
    builder.add_node("update_l2", mem.update_l2)

    # START → route
    builder.add_node("route_start", n.route_start)
    builder.add_edge(START, "route_start")
    builder.add_conditional_edges(
        "route_start",
        n.route_path,
        {"media_route": "media_route", "text_intent": "text_intent"},
    )

    # Media: media_route chooses ONE path via the route field.
    #   route == "extract" → legacy fan-out (extract ∥ research) → gate → analyst
    #   route == "rubric"  → split_pages → dual-track triage
    def _media_fanout(state: PipelineState):
        if state.get("route") == "rubric":
            return "split_pages"
        return ["extract", "research"]  # legacy parallel fan-out

    builder.add_conditional_edges(
        "media_route",
        _media_fanout,
        {
            "extract": "extract",
            "research": "research",
            "split_pages": "split_pages",
        },
    )

    # Legacy path: extract ∥ research → gate → analyst | short-circuit
    builder.add_edge("extract", "gate")
    builder.add_edge("research", "gate")
    builder.add_conditional_edges(
        "gate",
        n.after_extract,
        {
            "format_short_circuit": "format_short_circuit",
            "analyst": "analyst",
        },
    )
    builder.add_edge("analyst", "format_report")

    # Rubric dual-track path
    builder.add_edge("split_pages", "prepare_triage")
    builder.add_edge("prepare_triage", "triage_page")
    builder.add_edge("prepare_triage", "table_analyzer")
    builder.add_edge("triage_page", "accumulate")
    builder.add_edge("table_analyzer", "accumulate")
    builder.add_conditional_edges(
        "accumulate",
        tr.has_required,
        {"deterministic_calc": "deterministic_calc", "targeted_re_read": "targeted_re_read"},
    )
    builder.add_edge("targeted_re_read", "deterministic_calc")
    builder.add_edge("deterministic_calc", "layman_writer")
    builder.add_edge("layman_writer", "format_layman_report")

    # Text: intent → dispatch
    builder.add_conditional_edges(
        "text_intent",
        n.route_intent,
        {
            "text_answer": "text_answer",
            "status_reply": "status_reply",
            "confirm_action": "confirm_action",
        },
    )

    # Memory: after any reply-producing node, load memory then write (ordered).
    for reply_node in (
        "format_short_circuit",
        "format_report",
        "format_layman_report",
        "text_answer",
        "status_reply",
        "confirm_action",
    ):
        builder.add_edge(reply_node, "memory_load")

    builder.add_edge("memory_load", "write_l0")
    builder.add_edge("write_l0", "extract_l1")
    builder.add_conditional_edges(
        "extract_l1", _after_memory, {"merge_l3": "merge_l3", "update_l2": "update_l2"}
    )
    builder.add_edge("merge_l3", "update_l2")
    builder.add_edge("update_l2", END)

    return builder.compile(checkpointer=checkpointer, store=store)
