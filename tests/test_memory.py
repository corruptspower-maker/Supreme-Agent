"""Tests for the memory manager (episodic, semantic, procedural)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

# ─── MemoryManager ────────────────────────────────────────────────────────────


class TestMemoryManagerEpisodic:
    @pytest.fixture
    async def mem(self, tmp_path):
        """Return a started MemoryManager backed by tmp_path."""
        with patch("src.memory.manager.load_config") as mock_cfg:
            mock_cfg.return_value = {
                "memory": {
                    "episodic": {
                        "db_path": str(tmp_path / "episodic.db"),
                        "ttl_days": 90,
                    },
                    "semantic": {"enabled": False, "collection": "test"},
                    "procedural": {
                        "db_path": str(tmp_path / "procedural.db"),
                        "yaml_path": str(tmp_path / "workflows.yaml"),
                    },
                    "conversation": {"max_messages": 10},
                    "compaction": {"interval_minutes": 60},
                    "semantic_memory_enabled": False,
                    "semantic_search_timeout_seconds": 2.0,
                    "compaction_max_duration_seconds": 120,
                }
            }
            from src.memory.manager import MemoryManager

            m = MemoryManager()
            await m.start()
            return m

    async def test_store_and_search_episodic(self, mem):
        from src.core.models import MemoryEntry

        entry = MemoryEntry(
            category="test",
            content="Python is great for data science",
            importance=0.8,
        )
        await mem.store_episodic(entry)
        results = await mem.search_episodic("Python")
        assert len(results) >= 1
        assert any("Python" in r.content for r in results)

    async def test_search_episodic_no_match(self, mem):
        results = await mem.search_episodic("xyzzynonexistent")
        assert results == []

    async def test_search_returns_most_important_first(self, mem):
        from src.core.models import MemoryEntry

        low = MemoryEntry(category="test", content="low importance match", importance=0.1)
        high = MemoryEntry(category="test", content="high importance match", importance=0.9)
        await mem.store_episodic(low)
        await mem.store_episodic(high)

        results = await mem.search_episodic("importance match")
        assert results[0].importance >= results[-1].importance

    async def test_compact_removes_expired(self, mem):
        """compact() removes entries whose expires_at is in the past."""
        from datetime import datetime, timedelta, timezone
        from uuid import uuid4

        import aiosqlite

        past = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
        eid = str(uuid4())
        async with aiosqlite.connect(mem._episodic_path) as db:
            await db.execute(
                "INSERT INTO episodic (id, category, content, metadata, importance, access_count, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (eid, "test", "expired content", "{}", 0.5, 0, past, past),
            )
            await db.commit()

        await mem.compact()

        results = await mem.search_episodic("expired content")
        assert all(r.id != eid for r in results)


class TestMemoryManagerProcedural:
    @pytest.fixture
    async def mem(self, tmp_path):
        with patch("src.memory.manager.load_config") as mock_cfg:
            mock_cfg.return_value = {
                "memory": {
                    "episodic": {"db_path": str(tmp_path / "ep.db"), "ttl_days": 90},
                    "semantic": {"enabled": False, "collection": "t"},
                    "procedural": {
                        "db_path": str(tmp_path / "proc.db"),
                        "yaml_path": str(tmp_path / "wf.yaml"),
                    },
                    "conversation": {"max_messages": 10},
                    "compaction": {"interval_minutes": 60},
                    "semantic_memory_enabled": False,
                    "semantic_search_timeout_seconds": 2.0,
                    "compaction_max_duration_seconds": 120,
                }
            }
            from src.memory.manager import MemoryManager

            m = MemoryManager()
            await m.start()
            return m

    async def test_store_and_search_workflow(self, mem):
        wf_id = await mem.store_workflow(
            name="email_report",
            description="Send weekly report via email",
            steps=[{"tool": "email_tool", "action": "send"}],
        )
        assert wf_id

        results = await mem.search_workflows("report")
        assert any(w["name"] == "email_report" for w in results)

    async def test_record_workflow_outcome_updates_rate(self, mem):
        wf_id = await mem.store_workflow(
            name="backup_files",
            description="Back up important files",
            steps=[],
        )
        await mem.record_workflow_outcome(wf_id, success=True)
        await mem.record_workflow_outcome(wf_id, success=False)

        results = await mem.search_workflows("backup_files")
        assert len(results) == 1
        # 2 attempts: 1 success → rate = 0.5
        assert abs(results[0]["success_rate"] - 0.5) < 0.01
        assert results[0]["usage_count"] == 2

    async def test_yaml_synced_after_store(self, mem):
        await mem.store_workflow(
            name="sync_test",
            description="Test YAML sync",
            steps=[],
        )
        assert mem._workflows_path.exists()
        content = mem._workflows_path.read_text()
        assert "sync_test" in content


class TestMemoryManagerConversation:
    @pytest.fixture
    async def mem(self, tmp_path):
        with patch("src.memory.manager.load_config") as mock_cfg:
            mock_cfg.return_value = {
                "memory": {
                    "episodic": {"db_path": str(tmp_path / "ep.db"), "ttl_days": 90},
                    "semantic": {"enabled": False, "collection": "t"},
                    "procedural": {
                        "db_path": str(tmp_path / "proc.db"),
                        "yaml_path": str(tmp_path / "wf.yaml"),
                    },
                    "conversation": {"max_messages": 3},
                    "compaction": {"interval_minutes": 60},
                    "semantic_memory_enabled": False,
                    "semantic_search_timeout_seconds": 2.0,
                    "compaction_max_duration_seconds": 120,
                }
            }
            from src.memory.manager import MemoryManager

            m = MemoryManager()
            await m.start()
            return m

    async def test_conversation_buffer_truncates(self, mem):
        for i in range(5):
            mem.append_conversation("user", f"msg {i}")
        assert len(mem.get_conversation()) == 3  # max_messages = 3

    async def test_clear_conversation(self, mem):
        mem.append_conversation("user", "hello")
        mem.clear_conversation()
        assert mem.get_conversation() == []


class TestMemoryManagerSearch:
    @pytest.fixture
    async def mem(self, tmp_path):
        with patch("src.memory.manager.load_config") as mock_cfg:
            mock_cfg.return_value = {
                "memory": {
                    "episodic": {"db_path": str(tmp_path / "ep.db"), "ttl_days": 90},
                    "semantic": {"enabled": False, "collection": "t"},
                    "procedural": {
                        "db_path": str(tmp_path / "proc.db"),
                        "yaml_path": str(tmp_path / "wf.yaml"),
                    },
                    "conversation": {"max_messages": 50},
                    "compaction": {"interval_minutes": 60},
                    "semantic_memory_enabled": False,
                    "semantic_search_timeout_seconds": 2.0,
                    "compaction_max_duration_seconds": 120,
                }
            }
            from src.memory.manager import MemoryManager

            m = MemoryManager()
            await m.start()
            return m

    async def test_search_returns_string(self, mem):
        from src.core.models import MemoryEntry

        await mem.store_episodic(
            MemoryEntry(category="t", content="something about Python automation", importance=0.6)
        )
        result = await mem.search("Python automation")
        assert isinstance(result, str)

    async def test_store_task_result(self, mem):
        from src.core.models import Task, TaskStatus, ToolResult, UserRequest

        req = UserRequest(text="test task")
        task = Task(request=req, status=TaskStatus.COMPLETED)
        task.results = [ToolResult(tool_name="file_tool", success=True, output="Done writing file")]

        await mem.store_task_result(task)
        results = await mem.search_episodic("test task")
        assert len(results) >= 1
