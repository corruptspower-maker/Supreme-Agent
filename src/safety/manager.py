"""Safety manager — plan approval, rate limiting, forbidden-action blocking, audit logging."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
from loguru import logger

from src.core.models import AuditEntry, Plan, SafetyMode
from src.utils.config import load_config


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class SafetyManager:
    """Enforces safety rules over plans and tool executions.

    Responsibilities:
    - Approve or reject plans based on their constituent steps' risk levels.
    - Enforce per-action rate limits (e.g. max 5 emails/hour).
    - Block forbidden actions unconditionally.
    - Write an append-only audit log to SQLite.
    """

    def __init__(self) -> None:
        cfg = load_config("safety").get("safety", {})

        self._require_confirmation: set[str] = set(
            cfg.get("require_confirmation", [])
        )
        self._forbidden_actions: set[str] = set(cfg.get("forbidden_actions", []))
        self._audit_db_path = Path(cfg.get("audit_db_path", "data/audit.db"))

        # Rate limits: action_name -> {max, period_hours}
        self._rate_limits: dict[str, dict] = cfg.get("rate_limits", {})

        # In-memory sliding window: action_name -> list[unix_timestamp]
        self._action_timestamps: dict[str, list[float]] = {}

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialize the audit database."""
        self._audit_db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._audit_db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS audit (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    tool_name TEXT,
                    risk_level TEXT NOT NULL,
                    user_confirmed INTEGER,
                    input_summary TEXT NOT NULL,
                    output_summary TEXT,
                    success INTEGER NOT NULL,
                    error TEXT
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit(action)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(timestamp)"
            )
            await db.commit()
        logger.info("Safety manager started")

    # ─── Plan approval ────────────────────────────────────────────────────────

    async def check_plan(self, plan: Plan, safety_mode: SafetyMode) -> tuple[bool, str]:
        """Approve or reject a plan.

        Returns (approved: bool, reason: str).
        """
        if safety_mode == SafetyMode.SEVERE_LOCKED:
            return False, "Agent is in SEVERE_LOCKED safety mode — no plans allowed"

        for step in plan.steps:
            tool = step.tool_name or ""

            # Forbidden actions always blocked
            if tool in self._forbidden_actions:
                return False, f"Step '{step.description}' uses forbidden tool: {tool}"

            # In FULL mode, dangerous tools require explicit confirmation flag
            if safety_mode == SafetyMode.FULL and tool in self._require_confirmation:
                confirmed = step.tool_args.get("confirmed", False)
                if not confirmed:
                    return (
                        False,
                        f"Step '{step.description}' uses '{tool}' which requires "
                        "explicit confirmation (pass confirmed=True in tool_args)",
                    )

            # Rate limit check
            allowed, msg = self._check_rate_limit(tool)
            if not allowed:
                return False, f"Rate limit exceeded for '{tool}': {msg}"

        return True, "OK"

    # ─── Rate limiting ────────────────────────────────────────────────────────

    def _check_rate_limit(self, action: str) -> tuple[bool, str]:
        """Check if an action is within its configured rate limit.

        Returns (allowed: bool, message: str).
        """
        if action not in self._rate_limits:
            return True, ""

        limit_cfg = self._rate_limits[action]
        max_calls: int = int(limit_cfg.get("max", 100))
        period_hours: float = float(limit_cfg.get("period_hours", 1))
        period_seconds = period_hours * 3600

        now = time.time()
        window_start = now - period_seconds

        timestamps = self._action_timestamps.get(action, [])
        # Evict old timestamps
        timestamps = [t for t in timestamps if t >= window_start]
        self._action_timestamps[action] = timestamps

        if len(timestamps) >= max_calls:
            oldest = timestamps[0]
            retry_in = int(oldest + period_seconds - now)
            return False, f"max {max_calls} calls per {period_hours}h; retry in {retry_in}s"

        # Tentative: record now (committed after plan passes all checks)
        timestamps.append(now)
        self._action_timestamps[action] = timestamps
        return True, ""

    def record_action(self, action: str) -> None:
        """Explicitly record an action timestamp (call after successful execution)."""
        if action not in self._action_timestamps:
            self._action_timestamps[action] = []
        self._action_timestamps[action].append(time.time())

    # ─── Audit logging ────────────────────────────────────────────────────────

    async def log_audit(self, entry: AuditEntry) -> None:
        """Append an audit entry to the audit database."""
        try:
            async with aiosqlite.connect(self._audit_db_path) as db:
                await db.execute(
                    """
                    INSERT INTO audit
                        (id, timestamp, action, tool_name, risk_level, user_confirmed,
                         input_summary, output_summary, success, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.id,
                        entry.timestamp.isoformat(),
                        entry.action,
                        entry.tool_name,
                        entry.risk_level.value,
                        int(entry.user_confirmed) if entry.user_confirmed is not None else None,
                        entry.input_summary,
                        entry.output_summary,
                        int(entry.success),
                        entry.error,
                    ),
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Audit log write failed: {e}")

    async def get_recent_audit(self, limit: int = 50) -> list[dict]:
        """Return the most recent audit entries."""
        try:
            async with aiosqlite.connect(self._audit_db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM audit ORDER BY timestamp DESC LIMIT ?", (limit,)
                )
                rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Audit log read failed: {e}")
            return []
