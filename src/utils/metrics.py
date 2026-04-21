"""Lightweight SQLite-backed metrics counters."""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

_DB_PATH = Path("metrics.db")
_lock = asyncio.Lock()


def _init_db() -> sqlite3.Connection:
    """Open (or create) the metrics SQLite database and ensure the table exists."""
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS metrics (key TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0)"
    )
    conn.commit()
    return conn


_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    """Return the module-level database connection, initialising if needed."""
    global _conn
    if _conn is None:
        _conn = _init_db()
    return _conn


async def inc(key: str, amount: int = 1) -> None:
    """Increment a counter in the metrics table.

    Args:
        key: Metric name (e.g. 'tasks_total').
        amount: Amount to add to the current value.
    """
    async with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO metrics (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = value + excluded.value",
            (key, amount),
        )
        conn.commit()


def get_all() -> dict[str, int]:
    """Return all metric counters as a dictionary."""
    conn = _get_conn()
    rows = conn.execute("SELECT key, value FROM metrics").fetchall()
    return {row[0]: row[1] for row in rows}
