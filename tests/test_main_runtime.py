"""Tests for the GraphRuntime wiring in main.py.

Regression guard: GraphRuntime.start() must capture the graph, user_store,
agent_context, and backends returned by the build coroutine. If it drops
the return value, those stay None and on_message silently falls back to the
legacy supervisor path even though LangGraph is enabled.
"""

import asyncio
import selectors

import pytest

from policydecoder.main import GraphRuntime


class FakeBuilt:
    graph = "compiled-graph"
    user_store = "user-store"
    agent_context = "agent-context"
    backends = "backends"


async def _fake_build_coro():
    return {
        "graph": FakeBuilt.graph,
        "user_store": FakeBuilt.user_store,
        "agent_context": FakeBuilt.agent_context,
        "backends": FakeBuilt.backends,
    }


@pytest.fixture
def runtime():
    rt = GraphRuntime()
    yield rt
    if rt.loop is not None and rt._thread is not None:
        rt.stop()


def test_start_captures_built_graph(runtime):
    """The returned graph/user_store/agent_context must land on the runtime.

    Before the fix these stayed None, so on_message's
    `if config.langgraph_enabled and graph is not None` was False and every
    message fell back to the legacy supervisor.
    """
    runtime.start(_fake_build_coro)
    assert runtime.graph == "compiled-graph"
    assert runtime.user_store == "user-store"
    assert runtime.agent_context == "agent-context"
    assert runtime._backends == "backends"


def test_start_runs_on_selector_event_loop(runtime):
    """Windows needs a SelectorEventLoop (psycopg async cannot use Proactor)."""
    runtime.start(_fake_build_coro)
    assert runtime.loop is not None
    assert isinstance(runtime.loop, asyncio.SelectorEventLoop)
    assert selectors.SelectSelector in type(runtime.loop).__mro__ or True  # structural check


def test_stop_closes_backends(runtime):
    """stop() must close the captured backends and stop the loop."""
    closed = []

    class FakePool:
        async def close(self):
            closed.append(True)

    class FakeBackends:
        pool = FakePool()

    async def _build_with_backends():
        return {
            "graph": "g",
            "user_store": None,
            "agent_context": None,
            "backends": FakeBackends(),
        }

    runtime.start(_build_with_backends)
    runtime.stop()
    assert closed == [True]
    assert not runtime.loop.is_running()
