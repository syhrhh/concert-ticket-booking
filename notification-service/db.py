"""PostgreSQL access for the Notification Service: connection pool and start-up schema."""
import logging
import pathlib
from typing import Optional

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

import config

log = logging.getLogger("notification.db")

SQL_DIR = pathlib.Path(__file__).parent / "sql"
_MIGRATION_LOCK_ID = 724_003  # any constant; stops two instances racing on DDL

pool: Optional[ConnectionPool] = None


def init_pool() -> None:
    """Open the connection pool. Start-up fails fast if the database is down."""
    global pool
    pool = ConnectionPool(
        config.DATABASE_URL,
        min_size=1,
        max_size=config.DB_POOL_MAX,
        kwargs={"row_factory": dict_row, "options": "-c timezone=UTC"},
        open=False,
    )
    pool.open(wait=True, timeout=config.DB_CONNECT_TIMEOUT)
    log.info("database pool opened")


def close_pool() -> None:
    if pool is not None:
        pool.close()


def run_sql_file(name: str) -> None:
    """Apply a schema script from ./sql (safe to run on every start-up)."""
    sql = (SQL_DIR / name).read_text()
    with pool.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_ID,))
        conn.execute(sql)
    log.info("applied %s", name)


def ping() -> bool:
    try:
        with pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 - any failure means "not healthy"
        return False
