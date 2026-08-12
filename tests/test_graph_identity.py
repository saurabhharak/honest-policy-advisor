"""Tests for UserStore identity (stable user_id across email + Telegram)."""

import pytest

from policydecoder.graph.identity import UserStore


class FakeConn:
    """Minimal async psycopg-like connection that returns canned rows.

    Simulates a successful INSERT ... RETURNING user_id by yielding a fresh
    id when the executed SQL contains an INSERT, and an existing row from
    seed_rows for SELECTs.
    """

    def __init__(self, rows=None, next_id="fresh-id", insert_returns_row=True, select_results=None):
        self.rows = rows or []
        self.executed = []
        self.next_id = next_id
        self.insert_returns_row = insert_returns_row
        self.select_results = select_results or []  # per-SELECT results (consumed in order)
        self._select_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, params=None):
        self.executed.append(sql)
        return self

    async def fetchone(self):
        if self.executed and "INSERT INTO users" in self.executed[-1]:
            if self.insert_returns_row:
                return {"user_id": self.next_id}
            return None
        if self.select_results:
            self._select_count += 1
            return self.select_results[self._select_count - 1]
        if self.rows:
            return self.rows.pop(0)
        return None


class FakePool:
    """AsyncConnectionPool stand-in: connection() returns an async CM."""

    def __init__(
        self, seed_rows=None, next_id="fresh-id", insert_returns_row=True, select_results=None
    ):
        self.seed_rows = seed_rows or []
        self.conn = FakeConn(
            rows=list(self.seed_rows),
            next_id=next_id,
            insert_returns_row=insert_returns_row,
            select_results=select_results,
        )

    def connection(self):
        return self.conn


@pytest.mark.asyncio
async def test_get_or_create_creates_new_user():
    pool = FakePool(next_id="fresh-id")
    store = UserStore(pool)
    user_id = await store.get_or_create("a@b.c", "email")
    assert user_id == "fresh-id"
    # Second call with same contact returns the same id (no re-insert).
    pool.conn.rows = [{"user_id": user_id}]
    user_id2 = await store.get_or_create("a@b.c", "email")
    assert user_id2 == user_id


@pytest.mark.asyncio
async def test_get_or_create_creates_new_user_then_race_fallback():
    """INSERT returns nothing (race) → fallback SELECT returns the winner."""
    # SELECT 1 (pre-insert): None. INSERT: None (lost race). SELECT 2: winner.
    pool = FakePool(select_results=[None, {"user_id": "winner-id"}], insert_returns_row=False)
    store = UserStore(pool)
    user_id = await store.get_or_create("a@b.c", "email")
    assert user_id == "winner-id"


@pytest.mark.asyncio
async def test_get_or_create_returns_existing():
    pool = FakePool(seed_rows=[{"user_id": "existing-id"}])
    store = UserStore(pool)
    user_id = await store.get_or_create("a@b.c", "email")
    assert user_id == "existing-id"


@pytest.mark.asyncio
async def test_setup_creates_table():
    pool = FakePool()
    store = UserStore(pool)
    await store.setup()
    assert any("CREATE TABLE IF NOT EXISTS users" in sql for sql in pool.conn.executed)
