"""L0-L3 layered memory over LangGraph's MemoryStore.

Namespaces are all under the stable user_id so memory spans email + Telegram
and survives across threads:

- L0 raw:   (user_id, "l0", thread_id)   — raw message/event docs, no LLM.
- L1 atoms: (user_id, "l1", "atoms")     — atomic facts, keyed by content hash.
- L2 scena: (user_id, "l2", "scenarios") — per-policy knowledge bundles.
- L3 pers:  (user_id, "l3", "profile")   — single merged persona JSON doc.

Ordering: merge_l3 runs ONLY via a conditional edge from extract_l1 (it
consumes state["new_atoms"]); update_l2 runs only when an analysis completed.
Gating on meaningful events keeps L1/L3 LLM costs bounded.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from langgraph.runtime import Runtime

from policydecoder.config import get_config
from policydecoder.extractor import parse_json_response, response_text
from policydecoder.graph.state import GraphContext, PipelineState
from policydecoder.logging import get_logger
from policydecoder.opik_tracing import trace_llm
from policydecoder.prompts import MEMORY_EXTRACTION_PROMPT, PROFILE_MERGE_PROMPT

logger = get_logger("policydecoder.graph.memory")

# Namespaces
NS_L1 = ("l1", "atoms")
NS_L2 = ("l2", "scenarios")
NS_L3 = ("l3", "profile")

# Fixed embedding dimensions for the zero-vector fallback.
EMBED_DIMS = 1536


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _meaningful(state: PipelineState) -> bool:
    """Whether this turn produced a meaningful event worth LLM memory work."""
    if state.get("analysis"):
        return True
    return state.get("user_age") is not None


async def write_l0(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """Append a raw message/event doc to L0. No LLM, runs every turn."""
    user_id = runtime.context.user_id
    thread_id = (runtime.execution_info.thread_id if runtime.execution_info else None) or "unknown"
    ns = (user_id, "l0", thread_id)

    event: dict[str, Any] = {
        "role": "user",
        "ts": _now(),
        "text": state.get("text", ""),
        "media": bool(state.get("media_urls")),
    }
    if state.get("analysis"):
        event["event"] = "analysis"
        event["document_type"] = state.get("document_type")
    key = _hash(
        f"{thread_id}|{_now()}|{state.get('text', '')}|{len(state.get('media_urls') or [])}"
    )
    if runtime.store is not None:
        await runtime.store.aput(ns, key, event)
    return {}


def _memory_model(llm) -> str:
    """The model for memory LLM calls: client attr, else the configured LLM."""
    model = getattr(llm, "model", None)
    if model:
        return model
    return get_config().llm_model


def _llm_generate(llm, system: str, user: str, timeout: float = 15.0) -> str:
    """Single sync LLM call with tracing. Never raises (returns "" on failure)."""
    model = _memory_model(llm)
    try:
        response = llm.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.7,
            max_tokens=2000,
            timeout=timeout,
        )
        content = response_text(response)
        result = content.strip() if content else ""
        trace_llm(
            "memory_llm",
            model=model,
            input_text=user[:500],
            output_text=result[:500],
            metadata={"memory_layer": "l1_or_l3"},
        )
        return result
    except Exception as e:
        logger.warning("Memory LLM call failed: %s", e)
        return ""


def _memory_llm(runtime: Runtime[GraphContext]) -> Any:
    """The OpenAI client for memory LLM calls (from AgentContext)."""
    return runtime.context.agents.llm if runtime.context.agents else None


def _store(runtime: Runtime[GraphContext]):
    """Return the MemoryStore or None (mypy narrowing helper)."""
    return runtime.store


async def extract_l1(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """LLM-extract atomic facts into L1; return new_atoms for merge_l3.

    Gated: only runs on meaningful events (analysis completed, age captured).
    Upserts by content hash so repeated facts don't duplicate.
    """
    store = _store(runtime)
    if not _meaningful(state) or store is None:
        return {"new_atoms": []}

    conversation = f"Message: {state.get('text', '')}"
    if state.get("analysis"):
        conversation += f"\nAnalysis: {json.dumps(state['analysis'], ensure_ascii=False)[:1500]}"
    if state.get("policy_data"):
        conversation += f"\nPolicy: {json.dumps(state['policy_data'], ensure_ascii=False)[:1000]}"

    llm = _memory_llm(runtime)
    if llm is None:
        return {"new_atoms": []}

    prompt = MEMORY_EXTRACTION_PROMPT.format(conversation=conversation)
    content = _llm_generate(llm, "You are a memory extractor.", prompt, timeout=15)
    parsed = parse_json_response(content)
    facts = (parsed or {}).get("facts", []) if parsed else []

    user_id = runtime.context.user_id
    ns = (user_id,) + NS_L1
    new_atoms: list[str] = []
    for fact in facts:
        text = str(fact).strip()
        if not text:
            continue
        key = _hash(text)
        existing = await store.aget(ns, key)
        if existing is None:
            await store.aput(ns, key, {"fact": text, "ts": _now()})
            new_atoms.append(text)
    return {"new_atoms": new_atoms}


async def merge_l3(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """Merge new atoms into the L3 persona profile (hot path, only after L1)."""
    store = _store(runtime)
    new_atoms = state.get("new_atoms") or []
    if not new_atoms or store is None:
        return {}

    user_id = runtime.context.user_id
    ns = (user_id,) + NS_L3
    old = await store.aget(ns, "profile")
    old_profile = json.dumps(old.value if old else {}, ensure_ascii=False)

    llm = _memory_llm(runtime)
    if llm is None:
        return {}

    prompt = PROFILE_MERGE_PROMPT.format(
        old_profile=old_profile,
        new_facts="\n".join(f"- {a}" for a in new_atoms),
    )
    content = _llm_generate(llm, "You are a profile curator.", prompt, timeout=15)
    parsed = parse_json_response(content)
    profile = (parsed or {}).get("profile", {}) if parsed else {}
    if not profile:
        return {}
    await store.aput(ns, "profile", {"profile": profile, "ts": _now()})
    return {}


async def update_l2(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """Write/refresh a per-policy scenario bundle after an analysis completes."""
    store = _store(runtime)
    analysis = state.get("analysis")
    if not analysis or store is None:
        return {}

    policy = state.get("policy_data") or state.get("extraction") or {}
    name = policy.get("policy_name") or "policy"
    scenario = {
        "policy_name": name,
        "policy_type": policy.get("policy_type") or state.get("document_type"),
        "premium": policy.get("annual_premium"),
        "term": policy.get("policy_term_years"),
        "verdict": analysis.get("is_likely_missold") or analysis.get("verdict"),
        "recommended_action": analysis.get("recommended_action"),
        "summary": analysis.get("summary", ""),
        "ts": _now(),
    }

    user_id = runtime.context.user_id
    ns = (user_id,) + NS_L2
    key = _hash(name.lower())
    await store.aput(ns, key, scenario)
    return {}


async def memory_load(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """Assemble memory_context from L3 profile + semantic search of L1/L2.

    Runs right after route; the assembled markdown is injected into the
    intent-classifier and analyst prompts.
    """
    store = _store(runtime)
    user_id = runtime.context.user_id
    query = state.get("text", "") or "user insurance preferences"

    sections: list[str] = []

    # L3 profile
    ns3 = (user_id,) + NS_L3
    if store is not None:
        profile = await store.aget(ns3, "profile")
        if profile is not None:
            sections.append(
                "## User profile\n"
                + json.dumps(profile.value.get("profile", {}), ensure_ascii=False)
            )

        # L2 scenarios + L1 atoms via semantic search
        try:
            ns2 = (user_id,) + NS_L2
            scenarios = await store.asearch(ns2, query=query, limit=3)
            if scenarios:
                lines = []
                for item in scenarios:
                    v = item.value
                    lines.append(
                        f"- {v.get('policy_name', 'Policy')}: verdict={v.get('verdict')}, "
                        f"action={v.get('recommended_action')}"
                    )
                sections.append("## Known policies\n" + "\n".join(lines))
        except Exception as e:
            logger.warning("L2 search failed: %s", e)

        try:
            ns1 = (user_id,) + NS_L1
            atoms = await store.asearch(ns1, query=query, limit=5)
            if atoms:
                sections.append("## Facts\n" + "\n".join(f"- {a.value['fact']}" for a in atoms))
        except Exception as e:
            logger.warning("L1 search failed: %s", e)

    return {"memory_context": "\n\n".join(sections)}
