"""Tests for create_backends ordering: vector extension before store.setup()."""

import pytest

from policydecoder.graph import backends as b


class FakeAsyncConn:
    def __init__(self):
        self.executed = []

    async def execute(self, sql):
        self.executed.append(sql)
        return self


class FakePool:
    def __init__(self):
        self.conn = FakeAsyncConn()
        self.open_called = False

    async def open(self):
        self.open_called = True

    def connection(self):
        return _ConnCM(self.conn)


class _ConnCM:
    """Async context manager wrapper around FakeAsyncConn."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class FakeSaver:
    def __init__(self, pool):
        self.pool = pool
        self.setup_called = False

    async def setup(self):
        self.setup_called = True


class FakeStore:
    def __init__(self, pool, index=None):
        self.pool = pool
        self.index = index
        self.setup_called = False

    async def setup(self):
        self.setup_called = True


@pytest.mark.asyncio
async def test_create_backends_orders_vector_before_setup(monkeypatch):
    """The vector extension DDL must execute before store.setup() runs."""

    def fake_embed(texts):
        return [[0.0] * 1536 for _ in texts]

    pool = FakePool()
    # backends.py binds `from psycopg_pool import AsyncConnectionPool` at module
    # top, so patch the module-level name.
    monkeypatch.setattr(b, "AsyncConnectionPool", lambda *a, **k: pool)

    backends = await b.create_backends(
        "postgresql://x",
        embed=fake_embed,
        dims=1536,
        saver_factory=FakeSaver,
        store_factory=FakeStore,
    )

    assert pool.open_called is True
    # The extension DDL ran on the pool connection.
    assert any("CREATE EXTENSION IF NOT EXISTS vector" in sql for sql in pool.conn.executed)
    # setup() was awaited (idempotent migrations).
    assert backends.checkpointer.setup_called is True
    assert backends.store.setup_called is True
