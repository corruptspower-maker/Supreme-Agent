"""SQLite-backed audit log for escalation events."""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path

from src.core.models import EscalationLogEntry

_DB_PATH = Path("audit.db")
_lock = asyncio.Lock()


def _init_db(conn: sqlite3.Connection) -> None:
    """Create the audit table if it does not already exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit (
            id          TEXT PRIMARY KEY,
            task_id     TEXT NOT NULL,
            step_id     TEXT NOT NULL,
            event       TEXT NOT NULL,
            details     TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
        """
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()


_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    """Return the shared audit database connection, initialising if needed."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(
            str(_DB_PATH),
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
        )
        _init_db(_conn)
    return _conn


class AuditLog:
    """Async interface to the SQLite escalation audit log.

    All writes are serialised with an asyncio lock to prevent concurrent
    writes from corrupting the database.
    """

    async def log(self, entry: EscalationLogEntry) -> None:
        """Persist an EscalationLogEntry to the SQLite audit table.

        Args:
            entry: The EscalationLogEntry to store.
        """
        async with _lock:
            conn = _get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO audit (id, task_id, step_id, event, details, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    entry.id,
                    entry.task_id,
                    entry.step_id,
                    entry.event,
                    entry.details,
                    entry.created_at.isoformat(),
                ),
            )
            conn.commit()

    async def query(self, task_id: str) -> list[EscalationLogEntry]:
        """Retrieve all escalation audit entries for a given task.

        Args:
            task_id: The task whose audit trail to retrieve.

        Returns:
            List of EscalationLogEntry objects ordered by creation time.
        """
        async with _lock:
            conn = _get_conn()
            rows = conn.execute(
                "SELECT id, task_id, step_id, event, details, created_at FROM audit "
                "WHERE task_id = ? ORDER BY created_at",
                (task_id,),
            ).fetchall()
        return [
            EscalationLogEntry(
                id=row[0],
                task_id=row[1],
                step_id=row[2],
                event=row[3],
                details=row[4],
                created_at=datetime.fromisoformat(row[5]),
            )
            for row in rows
        ]
