"""
RailOS Shared PostgreSQL Utilities
====================================
Provides a context-managed database connection helper to replace the repeated
``psycopg2.connect(DB_URL) ... conn.commit(); conn.close()`` pattern found
across hazard_register, traceability_service, acknowledgement_service, and
retention_service.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Generator

log = logging.getLogger(__name__)

DEFAULT_DB_URL = os.environ.get(
    "DB_URL",
    "postgresql://railos:change-me@postgresql-primary.railos.svc.cluster.local:5432/railos",
)


@contextmanager
def pg_connection(db_url: str | None = None) -> Generator[Any, None, None]:
    """Context manager that yields a psycopg2 connection.

    Commits on clean exit, rolls back on exception, and always closes.

    Usage::

        with pg_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO ...")
    """
    import psycopg2  # deferred so modules without psycopg2 can still import

    conn = psycopg2.connect(db_url or DEFAULT_DB_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute_query(
    sql: str,
    params: tuple[Any, ...] | None = None,
    db_url: str | None = None,
) -> list[tuple[Any, ...]]:
    """Execute a SELECT query and return all rows.

    Returns an empty list on failure (logs the error).
    """
    try:
        with pg_connection(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
    except Exception as exc:
        log.error("DB query failed: %s", exc)
        return []


def execute_insert(
    sql: str,
    params: tuple[Any, ...] | None = None,
    db_url: str | None = None,
) -> bool:
    """Execute an INSERT/UPDATE statement. Returns True on success."""
    try:
        with pg_connection(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
        return True
    except Exception as exc:
        log.error("DB write failed: %s", exc)
        return False
