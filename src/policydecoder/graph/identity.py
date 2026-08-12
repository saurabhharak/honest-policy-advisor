"""User identity store — stable user_id shared across email and Telegram.

A `users` table maps (contact, channel) to a stable UUID user_id. Both
channels hit the same LangGraph MemoryStore namespaced by user_id, so a
user's policies and preferences carry across email and Telegram.

Uses the same shared AsyncConnectionPool as the checkpointer/store.
"""

from policydecoder.logging import get_logger

logger = get_logger("policydecoder.graph.identity")

_USERS_DDL = """
CREATE TABLE IF NOT EXISTS users (
    user_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact    TEXT NOT NULL,
    channel    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (contact, channel)
);
"""


class UserStore:
    def __init__(self, pool):
        self.pool = pool

    async def setup(self) -> None:
        """Create the users table (idempotent)."""
        async with self.pool.connection() as conn:
            await conn.execute(_USERS_DDL)

    async def get_or_create(self, contact: str, channel: str) -> str:
        """Return the stable user_id for (contact, channel), creating it if needed."""
        async with self.pool.connection() as conn:
            row = await conn.execute(
                "SELECT user_id FROM users WHERE contact = %s AND channel = %s",
                (contact, channel),
            )
            existing = await row.fetchone()
            if existing:
                return str(existing["user_id"])
            row = await conn.execute(
                """
                INSERT INTO users (contact, channel)
                VALUES (%s, %s)
                ON CONFLICT (contact, channel) DO NOTHING
                RETURNING user_id
                """,
                (contact, channel),
            )
            created = await row.fetchone()
            if created:
                return str(created["user_id"])
            # Lost a race — fetch the winner.
            row = await conn.execute(
                "SELECT user_id FROM users WHERE contact = %s AND channel = %s",
                (contact, channel),
            )
            winner = await row.fetchone()
            return str(winner["user_id"])
