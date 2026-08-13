"""Unit tests for eval datasets + task wrappers. No network."""

import asyncio

from policydecoder.evals import datasets
from policydecoder.evals.data import gold_rows, gold_version
from policydecoder.evals.tasks import make_sync_task


class TestGoldData:
    def test_all_agents_have_gold(self):
        for agent in (
            "router",
            "extractor",
            "researcher",
            "health_analyst",
            "life_analyst",
            "letter_drafter",
        ):
            assert gold_version(agent) >= 1
            assert len(gold_rows(agent)) > 0

    def test_gold_versions_consistent(self):
        # Every gold file has a positive integer version.
        for agent in (
            "router",
            "extractor",
            "researcher",
            "health_analyst",
            "life_analyst",
            "letter_drafter",
        ):
            assert isinstance(gold_version(agent), int)
            assert gold_version(agent) >= 1


class FakeDataset:
    def __init__(self):
        self.cleared = 0
        self.inserted = None

    def clear(self):
        self.cleared += 1

    def insert(self, rows):
        self.inserted = rows


class FakeClient:
    def __init__(self):
        self.datasets = {}

    def get_or_create_dataset(self, name, project_name=None, description=None):
        if name not in self.datasets:
            self.datasets[name] = FakeDataset()
        return self.datasets[name]


class TestSeeding:
    def test_seed_clears_then_inserts(self):
        client = FakeClient()
        rows = [{"a": 1}]
        datasets.seed_dataset(client, "router", rows)
        ds = client.datasets["policy-router-gold"]
        assert ds.cleared == 1
        assert ds.inserted == rows

    def test_get_or_create_dataset_name(self):
        client = FakeClient()
        ds = datasets.get_or_create_dataset(client, "extractor")
        assert ds is client.datasets["policy-extractor-gold"]


class TestSyncTask:
    def test_sync_task_runs_async_runner(self):
        async def runner(inputs):
            return {"echoed": inputs["x"] + 1}

        task = make_sync_task(runner)
        out = task({"inputs": {"x": 1}, "echo": {"ref": 2}})
        assert out["output"] == {"echoed": 2}
        assert out["ref"] == 2

    def test_sync_task_isolated_loops(self):
        """Two consecutive calls must not share an event loop."""
        loops = []

        async def runner(inputs):
            loops.append(asyncio.get_running_loop())
            return {}

        task = make_sync_task(runner)
        task({"inputs": {}})
        task({"inputs": {}})
        assert len(loops) == 2
        assert loops[0] is not loops[1]
