"""Opik dataset management for the eval harness.

Seeding is deterministic: clear() then insert() so the dataset is pinned
exactly to the current gold file content (Opik dedupes by content hash,
so plain insert() would accumulate stale rows across gold edits).
"""

from typing import Any

from policydecoder.evals.config import OPIK_PROJECT
from policydecoder.evals.data import gold_rows, gold_version


def get_or_create_dataset(client: Any, agent: str):
    """Get (or create) the Opik dataset for an agent."""
    name = f"policy-{agent}-gold"
    return client.get_or_create_dataset(
        name=name,
        project_name=OPIK_PROJECT,
        description=f"Gold evaluation data for the {agent} agent (version {gold_version(agent)}).",
    )


def seed_dataset(client: Any, agent: str, rows: list[dict[str, Any]] | None = None) -> None:
    """Pin the agent's dataset to the current gold rows (clear + insert)."""
    rows = rows if rows is not None else gold_rows(agent)
    dataset = get_or_create_dataset(client, agent)
    dataset.clear()
    dataset.insert(rows)
