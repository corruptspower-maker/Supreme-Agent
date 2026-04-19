"""Memory manager — episodic (SQLite), semantic (ChromaDB), procedural (YAML)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import yaml
from loguru import logger

from src.core.models import MemoryEntry, Task
from src.utils.config import load_config


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class MemoryManager:
    """Unified memory manager for the Executive Agent.

    Manages three memory stores:
    - Episodic: short-term SQLite store of task outcomes.
    - Semantic: optional ChromaDB vector search (degrades gracefully).
    - Procedural: YAML-backed workflow/procedure store + SQLite index.
    """

    def __init__(self) -> None:
        cfg = load_config("memory").get("memory", {})

        episodic_cfg = cfg.get("episodic", {})
        self._episodic_path = Path(episodic_cfg.get("db_path", "data/episodic.db"))
        self._episodic_ttl_days: int = int(episodic_cfg.get("ttl_days", 90))

        semantic_cfg = cfg.get("semantic", {})
        self._semantic_enabled: bool = bool(cfg.get("semantic_memory_enabled", True))
        self._semantic_collection_name: str = semantic_cfg.get("collection", "semantic_memory")
        self._semantic_timeout: float = float(
            cfg.get("semantic_search_timeout_seconds", 2.0)
        )

        procedural_cfg = cfg.get("procedural", {})
        self._procedural_path = Path(procedural_cfg.get("db_path", "data/procedural.db"))
        self._workflows_path = Path(procedural_cfg.get("yaml_path", "data/workflows.yaml"))

        self._compaction_interval: int = int(
            cfg.get("compaction", {}).get("interval_minutes", 60)
        ) * 60  # convert to seconds
        self._compaction_max_duration: int = int(
            cfg.get("compaction_max_duration_seconds", 120)
        )

        self._chroma_client = None
        self._chroma_collection = None
        self._conversation: list[dict] = []
        self._max_conversation: int = int(
            cfg.get("conversation", {}).get("max_messages", 50)
        )

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialize all memory stores."""
        self._episodic_path.parent.mkdir(parents=True, exist_ok=True)
        self._procedural_path.parent.mkdir(parents=True, exist_ok=True)
        self._workflows_path.parent.mkdir(parents=True, exist_ok=True)

        await self._init_episodic()
        await self._init_procedural()
        await self._init_semantic()

        logger.info("Memory manager started")

    async def _init_episodic(self) -> None:
        async with aiosqlite.connect(self._episodic_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS episodic (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    importance REAL NOT NULL DEFAULT 0.5,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    expires_at TEXT
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_episodic_category ON episodic(category)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_episodic_created ON episodic(created_at)"
            )
            await db.commit()
        logger.debug("Episodic memory DB ready")

    async def _init_procedural(self) -> None:
        async with aiosqlite.connect(self._procedural_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    steps TEXT NOT NULL DEFAULT '[]',
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    success_rate REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_workflows_name ON workflows(name)"
            )
            await db.commit()
        logger.debug("Procedural memory DB ready")

    async def _init_semantic(self) -> None:
        if not self._semantic_enabled:
            logger.info("Semantic memory disabled by config")
            return
        try:
            import chromadb  # type: ignore

            self._chroma_client = chromadb.Client()
            self._chroma_collection = self._chroma_client.get_or_create_collection(
                self._semantic_collection_name
            )
            logger.info("Semantic memory (ChromaDB) ready")
        except ImportError:
            logger.warning("ChromaDB not installed — semantic memory disabled")
            self._semantic_enabled = False
        except Exception as e:
            logger.warning(f"ChromaDB init failed — semantic memory disabled: {e}")
            self._semantic_enabled = False

    # ─── Episodic memory ──────────────────────────────────────────────────────

    async def store_episodic(self, entry: MemoryEntry) -> None:
        """Persist an episodic memory entry to SQLite."""
        expires_at = None
        if self._episodic_ttl_days > 0:
            expires_at = (
                _utcnow() + timedelta(days=self._episodic_ttl_days)
            ).isoformat()

        async with aiosqlite.connect(self._episodic_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO episodic
                    (id, category, content, metadata, importance, access_count, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.id,
                    entry.category,
                    entry.content,
                    json.dumps(entry.metadata),
                    entry.importance,
                    entry.access_count,
                    entry.timestamp.isoformat(),
                    expires_at,
                ),
            )
            await db.commit()

    async def search_episodic(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        """Full-text search over episodic memory content."""
        async with aiosqlite.connect(self._episodic_path) as db:
            db.row_factory = aiosqlite.Row
            # Simple keyword search across content; semantic search handled by ChromaDB
            pattern = f"%{query}%"
            now_iso = _utcnow().isoformat()
            cursor = await db.execute(
                """
                SELECT * FROM episodic
                WHERE content LIKE ?
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY importance DESC, created_at DESC
                LIMIT ?
                """,
                (pattern, now_iso, limit),
            )
            rows = await cursor.fetchall()

        entries = []
        for row in rows:
            entries.append(
                MemoryEntry(
                    id=row["id"],
                    category=row["category"],
                    content=row["content"],
                    metadata=json.loads(row["metadata"]),
                    importance=row["importance"],
                    access_count=row["access_count"],
                    timestamp=datetime.fromisoformat(row["created_at"]),
                )
            )
        return entries

    # ─── Semantic memory ──────────────────────────────────────────────────────

    async def store_semantic(self, entry: MemoryEntry) -> None:
        """Add a document to the semantic (vector) memory."""
        if not self._semantic_enabled or self._chroma_collection is None:
            return
        try:
            await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._chroma_collection.add(
                        ids=[entry.id],
                        documents=[entry.content],
                        metadatas=[{"category": entry.category, **entry.metadata}],
                    ),
                ),
                timeout=self._semantic_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Semantic memory store timed out")
        except Exception as e:
            logger.warning(f"Semantic memory store error: {e}")

    async def search_semantic(self, query: str, n_results: int = 5) -> list[str]:
        """Query ChromaDB for semantically similar content."""
        if not self._semantic_enabled or self._chroma_collection is None:
            return []
        try:
            results = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._chroma_collection.query(
                        query_texts=[query], n_results=n_results
                    ),
                ),
                timeout=self._semantic_timeout,
            )
            return results.get("documents", [[]])[0]
        except asyncio.TimeoutError:
            logger.warning("Semantic memory search timed out")
            return []
        except Exception as e:
            logger.warning(f"Semantic memory search error: {e}")
            return []

    # ─── Procedural memory ────────────────────────────────────────────────────

    async def store_workflow(
        self,
        name: str,
        description: str,
        steps: list[dict],
    ) -> str:
        """Persist a procedural workflow to SQLite and YAML."""
        from uuid import uuid4

        wf_id = str(uuid4())
        now_iso = _utcnow().isoformat()

        async with aiosqlite.connect(self._procedural_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO workflows
                    (id, name, description, steps, usage_count, success_rate, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, 1.0, ?, ?)
                """,
                (wf_id, name, description, json.dumps(steps), now_iso, now_iso),
            )
            await db.commit()

        await self._sync_workflows_yaml()
        logger.debug(f"Workflow stored: {name}")
        return wf_id

    async def search_workflows(self, query: str, limit: int = 5) -> list[dict]:
        """Search procedural workflows by name or description."""
        pattern = f"%{query}%"
        async with aiosqlite.connect(self._procedural_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM workflows
                WHERE name LIKE ? OR description LIKE ?
                ORDER BY usage_count DESC, success_rate DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            )
            rows = await cursor.fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "steps": json.loads(r["steps"]),
                "usage_count": r["usage_count"],
                "success_rate": r["success_rate"],
            }
            for r in rows
        ]

    async def record_workflow_outcome(self, wf_id: str, success: bool) -> None:
        """Update usage count and rolling success rate for a workflow."""
        async with aiosqlite.connect(self._procedural_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT usage_count, success_rate FROM workflows WHERE id = ?",
                (wf_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return
            n = row["usage_count"]
            old_rate = row["success_rate"]
            new_count = n + 1
            new_rate = (old_rate * n + (1.0 if success else 0.0)) / new_count
            await db.execute(
                "UPDATE workflows SET usage_count = ?, success_rate = ?, updated_at = ? WHERE id = ?",
                (new_count, new_rate, _utcnow().isoformat(), wf_id),
            )
            await db.commit()

    async def _sync_workflows_yaml(self) -> None:
        """Dump all workflows to the YAML file for human inspection."""
        try:
            async with aiosqlite.connect(self._procedural_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("SELECT * FROM workflows ORDER BY name")
                rows = await cursor.fetchall()
            data = [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "description": r["description"],
                    "steps": json.loads(r["steps"]),
                    "usage_count": r["usage_count"],
                    "success_rate": r["success_rate"],
                }
                for r in rows
            ]
            self._workflows_path.write_text(yaml.safe_dump({"workflows": data}))
        except Exception as e:
            logger.warning(f"Workflow YAML sync failed: {e}")

    # ─── Conversation buffer ──────────────────────────────────────────────────

    def append_conversation(self, role: str, content: str) -> None:
        """Append a message to the in-memory conversation buffer."""
        self._conversation.append({"role": role, "content": content})
        if len(self._conversation) > self._max_conversation:
            self._conversation = self._conversation[-self._max_conversation:]

    def get_conversation(self) -> list[dict]:
        """Return the current conversation buffer."""
        return list(self._conversation)

    def clear_conversation(self) -> None:
        """Reset the conversation buffer."""
        self._conversation = []

    # ─── High-level helpers ───────────────────────────────────────────────────

    async def search(self, query: str) -> str:
        """Search all memory stores and return a combined context string."""
        parts: list[str] = []

        # Semantic search first (higher quality)
        semantic_hits = await self.search_semantic(query, n_results=3)
        if semantic_hits:
            parts.append("Relevant knowledge:\n" + "\n".join(f"- {h}" for h in semantic_hits))

        # Episodic search
        episodic_hits = await self.search_episodic(query, limit=3)
        if episodic_hits:
            parts.append(
                "Past task outcomes:\n"
                + "\n".join(f"- [{e.category}] {e.content}" for e in episodic_hits)
            )

        # Procedural search
        workflows = await self.search_workflows(query, limit=2)
        if workflows:
            names = ", ".join(w["name"] for w in workflows)
            parts.append(f"Known workflows: {names}")

        return "\n\n".join(parts)

    async def store_task_result(self, task: Task) -> None:
        """Store a completed task's outcome in episodic and semantic memory."""
        if not task.results:
            return

        outputs = [r.output for r in task.results if r.success and r.output]
        combined = "\n".join(outputs)
        if not combined:
            return

        importance = 0.8 if task.status.value == "completed" else 0.4
        entry = MemoryEntry(
            category="task_outcome",
            content=f"Task: {task.request.text}\nOutcome: {combined[:500]}",
            metadata={"task_id": task.id, "status": task.status.value},
            importance=importance,
        )
        await self.store_episodic(entry)
        await self.store_semantic(entry)

    # ─── Compaction ───────────────────────────────────────────────────────────

    async def compact(self) -> None:
        """Remove expired episodic entries."""
        try:
            now_iso = _utcnow().isoformat()
            async with aiosqlite.connect(self._episodic_path) as db:
                cursor = await db.execute(
                    "DELETE FROM episodic WHERE expires_at IS NOT NULL AND expires_at <= ?",
                    (now_iso,),
                )
                deleted = cursor.rowcount
                await db.commit()
            if deleted:
                logger.info(f"Memory compaction removed {deleted} expired entries")
        except Exception as e:
            logger.warning(f"Memory compaction error: {e}")

    async def compaction_loop(self) -> None:
        """Background loop that periodically compacts expired memory."""
        while True:
            await asyncio.sleep(self._compaction_interval)
            await self.compact()
