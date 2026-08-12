"""Tests for PromptStore: seed/load rubric from InMemoryStore, version upsert."""

import pytest
from langgraph.store.memory import InMemoryStore

from policydecoder.graph.prompt_store import PromptStore, seed_rubrics
from policydecoder.graph.rubrics import PRODUCTS


def _make_store():
    return InMemoryStore()


@pytest.mark.asyncio
async def test_seed_rubrics_loads_all_products():
    store = _make_store()
    await seed_rubrics(store)
    ps = PromptStore(store)
    for product in PRODUCTS:
        rubric = await ps.load_rubric(product)
        assert rubric is not None
        assert rubric["product"] == product


@pytest.mark.asyncio
async def test_seed_is_idempotent():
    store = _make_store()
    await seed_rubrics(store)
    await seed_rubrics(store)  # second seed must not error / duplicate
    ps = PromptStore(store)
    rubric = await ps.load_rubric("HEALTH")
    assert rubric["version"] == 1


@pytest.mark.asyncio
async def test_save_and_load_prompt():
    store = _make_store()
    ps = PromptStore(store)
    await ps.save_prompt("HEALTH", "triage_prompt", "TEXT")
    loaded = await ps.load_prompt("HEALTH", "triage_prompt")
    assert loaded == "TEXT"


@pytest.mark.asyncio
async def test_version_namespace_isolation():
    store = _make_store()
    ps = PromptStore(store)
    await ps.save_rubric("HEALTH", {"product": "HEALTH", "version": 1})
    await ps.save_rubric("HEALTH", {"product": "HEALTH", "version": 2})
    v1 = await ps.load_rubric("HEALTH", "v1")
    v2 = await ps.load_rubric("HEALTH", "v2")
    assert v1["version"] == 1
    assert v2["version"] == 2
