"""PromptStore — stores per-product rubrics as namespaced JSON in the shared store.

LangGraph's official pattern stores prompts as namespaced JSON docs in the same
BaseStore/MemoryStore used for long-term memory. We reuse our existing
AsyncPostgresStore (from graph/backends.py) — no new infra.

Namespaces:
    ("rubrics", <product>, "v<version>") → key "rubric"       holds the rubric JSON
                                            key "triage_prompt" / "layman_prompt"
                                                              hold rendered prompt templates

The store is the source of truth at startup (seed_rubrics). During a graph run,
the rubric is loaded ONCE by the prepare_triage node into graph state — the
parallel triage nodes read from state, so there are ZERO repeat DB queries for
static data.
"""

import json
from typing import Any

from policydecoder.graph.rubrics import PRODUCTS, load_rubric_file


class PromptStore:
    def __init__(self, store):
        self.store = store

    def _ns(self, product: str, version: str) -> tuple[str, ...]:
        return ("rubrics", product, version)

    async def load_rubric(self, product: str, version: str = "v1") -> dict[str, Any] | None:
        item = await self.store.aget(self._ns(product, version), "rubric")
        return item.value if item else None

    async def save_rubric(self, product: str, rubric: dict[str, Any]) -> None:
        version = f"v{rubric.get('version', 1)}"
        await self.store.aput(self._ns(product, version), "rubric", rubric)

    async def load_prompt(self, product: str, which: str, version: str = "v1") -> str | None:
        item = await self.store.aget(self._ns(product, version), which)
        return item.value.get("text") if item and item.value else None

    async def save_prompt(self, product: str, which: str, text: str, version: str = "v1") -> None:
        await self.store.aput(self._ns(product, version), which, {"text": text})


async def seed_rubrics(store) -> None:
    """Load data/rubrics/*.json into the store (idempotent upsert by product+version)."""
    ps = PromptStore(store)
    for product in PRODUCTS:
        rubric = load_rubric_file(product)
        await ps.save_rubric(product, rubric)


def rubric_to_json(rubric: dict[str, Any]) -> str:
    """Serialize a rubric to JSON for embedding in a prompt."""
    return json.dumps(rubric, ensure_ascii=False)
