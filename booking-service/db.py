"""PostgreSQL access: connection pool, start-up migration and outbox helper."""
import logging
import pathlib
from typing import Any, Dict, Optional

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

import config

log = logging.getLogger("booking.db")

SQL_DIR = pathlib.Path(__file__).parent / "sql"
_MIGRATION_LOCK_ID = 724_001  # arbitrary constant for pg_advisory_xact_lock

pool: Optional[ConnectionPool] = None


def init_pool() -> None:
    """Open the shared connection pool (fails fast if the database is down)."""
    global pool
    pool = ConnectionPool(
        config.DATABASE_URL,
        min_size=1,
        max_size=config.DB_POOL_MAX,
        # UTC everywhere so timestamp comparisons in SQL are unambiguous.
        kwargs={"row_factory": dict_row, "options": "-c timezone=UTC"},
        open=False,
    )
    pool.open(wait=True, timeout=config.DB_CONNECT_TIMEOUT)
    log.info("database pool opened")


def close_pool() -> None:
    if pool is not None:
        pool.close()


def run_sql_file(name: str) -> None:
    """Run a script from ./sql. The advisory lock serialises start-up of
    several Booking Service instances so they do not race on DDL."""
    sql = (SQL_DIR / name).read_text()
    with pool.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_ID,))
        conn.execute(sql)
    log.info("applied %s", name)


def enqueue(conn, booking_id: str, kind: str, payload: Dict[str, Any]) -> None:
    """Add a side effect to the outbox using the caller's transaction, so it is
    committed atomically with the booking state change."""
    conn.execute(
        "INSERT INTO booking_outbox (booking_id, kind, payload) VALUES (%s, %s, %s)",
        (booking_id, kind, Jsonb(payload)),
    )


def ping() -> bool:
    try:
        with pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 - any failure means "not healthy"
        return False
