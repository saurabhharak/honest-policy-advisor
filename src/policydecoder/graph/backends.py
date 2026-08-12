"""Postgres backends for LangGraph persistence and memory.

Owns the shared AsyncConnectionPool and constructs the AsyncPostgresSaver
(checkpointer) + AsyncPostgresStore (long-term memory) on it, plus the
UserStore identity table.

Ordering matters (review feedback):
- The vector extension MUST be created before store.setup(), otherwise the
  embedding-index DDL throws a cryptic syntax error.
- checkpointer.setup() / store.setup() are awaited (idempotent schema
  migrations) before the graph is compiled.

One shared pool across checkpointer, store, and UserStore avoids connection
exhaustion and keeps a single teardown surface.
"""

from collections.abc import Callable

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from policydecoder.logging import get_logger

logger = get_logger("policydecoder.graph.backends")


class Backends:
    """Container for the shared pool + LangGraph persistence components."""

    def __init__(self, pool, checkpointer, store):
        self.pool = pool
        self.checkpointer = checkpointer
        self.store = store


async def create_backends(
    dsn: str,
    embed: Callable[[list[str]], list[list[float]]],
    dims: int = 1536,
    pool_size: int = 5,
    saver_factory=None,
    store_factory=None,
) -> Backends:
    """Create the pool, ensure the vector extension, and run setup().

    Must run once on the persistent event loop before compiling/invoking
    the graph.

    saver_factory / store_factory: optional constructors for tests to inject
    fakes; default to the LangGraph Postgres classes.
    """
    if saver_factory is None:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        saver_factory = AsyncPostgresSaver
    if store_factory is None:
        from langgraph.store.postgres.aio import AsyncPostgresStore

        store_factory = AsyncPostgresStore

    # LangGraph's saver/store require dict rows and autocommit (its migrations
    # use CREATE INDEX CONCURRENTLY, which cannot run inside a transaction).
    # Configure the pool's connections accordingly.
    pool = AsyncConnectionPool(
        dsn,
        min_size=1,
        max_size=pool_size,
        open=False,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    await pool.open()

    # MUST run before store.setup(): the extension is required for the
    # embedding index DDL.
    async with pool.connection() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    checkpointer = saver_factory(pool)
    store = store_factory(pool, index={"embed": embed, "dims": dims})

    await checkpointer.setup()  # awaited, idempotent schema migrations
    await store.setup()  # awaited, idempotent

    return Backends(pool=pool, checkpointer=checkpointer, store=store)


async def close_backends(backends: Backends) -> None:
    """Graceful teardown: cancel pending work then close the pool."""
    if backends is None:
        return
    try:
        await backends.pool.close()
    except Exception as e:
        logger.warning("Error closing Postgres pool: %s", e)
