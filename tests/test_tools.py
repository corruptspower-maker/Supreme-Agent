"""Tests for src/tools/ — all tool implementations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# ─── BaseTool ────────────────────────────────────────────────────────────────

class TestBaseTool:
    def _make_tool(self):

        from src.core.models import RiskLevel, ToolResult
        from src.tools.base import BaseTool

        class DummyTool(BaseTool):
            name = "dummy_tool"
            description = "A dummy tool for testing"
            risk_level = RiskLevel.SAFE
            parameters_schema = {"type": "object", "properties": {}}

            async def execute(self, **kwargs):
                return ToolResult(tool_name=self.name, success=True, output="ok")

            async def validate_args(self, **kwargs):
                return True, ""

        return DummyTool()

    def test_to_mcp_schema(self):
        tool = self._make_tool()
        schema = tool.to_mcp_schema()
        assert schema["name"] == "dummy_tool"
        assert schema["description"] == "A dummy tool for testing"
        assert schema["risk_level"] == "safe"
        assert "parameters" in schema

    def test_to_prompt_description(self):
        tool = self._make_tool()
        desc = tool.to_prompt_description()
        assert "dummy_tool" in desc
        assert "safe" in desc

    def test_timed_result_has_execution_time(self):
        import time
        tool = self._make_tool()
        start = time.monotonic()
        result = tool._timed_result(start, True, output="hello")
        assert result.execution_time_ms >= 0
        assert result.success is True
        assert result.output == "hello"


# ─── ToolRegistry ────────────────────────────────────────────────────────────

class TestToolRegistry:
    def test_register_and_get(self):
        from src.tools.file_tool import FileTool
        from src.tools.registry import ToolRegistry

        reg = ToolRegistry()
        tool = FileTool()
        reg.register(tool)
        assert reg.get("file_tool") is tool

    def test_register_no_name_raises(self):
        from src.core.models import ToolResult
        from src.tools.base import BaseTool
        from src.tools.registry import ToolRegistry

        class NoNameTool(BaseTool):
            name = ""

            async def execute(self, **kwargs):
                return ToolResult(tool_name="", success=True)

            async def validate_args(self, **kwargs):
                return True, ""

        reg = ToolRegistry()
        with pytest.raises(ValueError):
            reg.register(NoNameTool())

    def test_contains_and_len(self):
        from src.tools.file_tool import FileTool
        from src.tools.registry import ToolRegistry

        reg = ToolRegistry()
        reg.register(FileTool())
        assert "file_tool" in reg
        assert len(reg) == 1

    def test_record_result_stats(self):
        from src.tools.file_tool import FileTool
        from src.tools.registry import ToolRegistry

        reg = ToolRegistry()
        reg.register(FileTool())
        reg.record_result("file_tool", success=True)
        reg.record_result("file_tool", success=False)
        stats = reg.get_stats()
        assert stats["file_tool"]["calls"] == 2
        assert stats["file_tool"]["successes"] == 1
        assert stats["file_tool"]["failures"] == 1

    def test_get_unknown_returns_none(self):
        from src.tools.registry import ToolRegistry
        reg = ToolRegistry()
        assert reg.get("nonexistent") is None

    def test_autodiscover(self):
        from src.tools.registry import ToolRegistry
        reg = ToolRegistry()
        count = reg.autodiscover()
        assert count >= 5  # file, shell, python, web_search, email, rag
        assert "file_tool" in reg

    def test_list_tools(self):
        from src.tools.file_tool import FileTool
        from src.tools.registry import ToolRegistry
        reg = ToolRegistry()
        reg.register(FileTool())
        tools = reg.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "file_tool"


# ─── FileTool ────────────────────────────────────────────────────────────────

class TestFileTool:
    async def test_read_nonexistent_file(self):
        from src.tools.file_tool import FileTool
        tool = FileTool()
        result = await tool.execute(action="read", path="/nonexistent/path/file.txt")
        assert result.success is False
        assert "not found" in result.error.lower()

    async def test_write_and_read(self, tmp_path):
        from src.tools.file_tool import FileTool
        tool = FileTool()
        filepath = str(tmp_path / "test.txt")

        write_result = await tool.execute(action="write", path=filepath, content="hello world")
        assert write_result.success is True

        read_result = await tool.execute(action="read", path=filepath)
        assert read_result.success is True
        assert read_result.output == "hello world"

    async def test_list_directory(self, tmp_path):
        from src.tools.file_tool import FileTool
        tool = FileTool()
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")

        result = await tool.execute(action="list", path=str(tmp_path))
        assert result.success is True
        assert "a.txt" in result.output
        assert "b.txt" in result.output

    async def test_search_with_pattern(self, tmp_path):
        from src.tools.file_tool import FileTool
        tool = FileTool()
        (tmp_path / "found.txt").write_text("data")
        (tmp_path / "other.py").write_text("code")

        result = await tool.execute(action="search", path=str(tmp_path), pattern="*.txt")
        assert result.success is True
        assert "found.txt" in result.output

    async def test_delete_file(self, tmp_path):
        from src.tools.file_tool import FileTool
        tool = FileTool()
        f = tmp_path / "del.txt"
        f.write_text("bye")

        result = await tool.execute(action="delete", path=str(f))
        assert result.success is True
        assert not f.exists()

    async def test_delete_nonexistent_file(self, tmp_path):
        from src.tools.file_tool import FileTool
        tool = FileTool()
        result = await tool.execute(action="delete", path=str(tmp_path / "missing.txt"))
        assert result.success is False

    async def test_write_dry_run(self, tmp_path):
        from src.tools.file_tool import FileTool
        tool = FileTool()
        filepath = str(tmp_path / "dry.txt")

        result = await tool.execute(action="write", path=filepath, content="test", dry_run=True)
        assert result.success is True
        assert "dry-run" in result.output
        assert not Path(filepath).exists()

    async def test_validate_args_unknown_action(self):
        from src.tools.file_tool import FileTool
        tool = FileTool()
        valid, msg = await tool.validate_args(action="explode", path="/tmp")
        assert valid is False
        assert "Unknown action" in msg

    async def test_validate_args_write_requires_content(self):
        from src.tools.file_tool import FileTool
        tool = FileTool()
        valid, msg = await tool.validate_args(action="write", path="/tmp/x.txt")
        assert valid is False
        assert "content" in msg


# ─── ShellTool ────────────────────────────────────────────────────────────────

class TestShellTool:
    async def test_rm_not_in_whitelist(self):
        from src.tools.shell_tool import ShellTool
        tool = ShellTool()
        valid, msg = await tool.validate_args(command="rm -rf /")
        assert valid is False
        assert "not in whitelist" in msg

    async def test_echo_in_whitelist(self):
        from src.tools.shell_tool import ShellTool
        tool = ShellTool()
        valid, msg = await tool.validate_args(command="echo hello")
        assert valid is True

    async def test_execute_echo_dry_run(self):
        from src.tools.shell_tool import ShellTool
        tool = ShellTool()
        result = await tool.execute(command="echo hello", dry_run=True)
        assert result.success is True
        assert "dry-run" in result.output

    async def test_execute_echo_real(self):
        from src.tools.shell_tool import ShellTool
        tool = ShellTool()
        result = await tool.execute(command="echo hello_test")
        assert result.success is True
        assert "hello_test" in result.output

    async def test_empty_command_invalid(self):
        from src.tools.shell_tool import ShellTool
        tool = ShellTool()
        valid, msg = await tool.validate_args(command="")
        assert valid is False


# ─── PythonTool ────────────────────────────────────────────────────────────────

class TestPythonTool:
    async def test_allowed_import_json(self):
        from src.tools.python_tool import PythonTool
        tool = PythonTool()
        valid, msg = await tool.validate_args(code="import json\nprint(json.dumps({'a': 1}))")
        assert valid is True

    async def test_disallowed_import_os(self):
        from src.tools.python_tool import PythonTool
        tool = PythonTool()
        valid, msg = await tool.validate_args(code="import os\nos.system('rm -rf /')")
        assert valid is False
        assert "not allowed" in msg

    async def test_execute_valid_code(self):
        from src.tools.python_tool import PythonTool
        tool = PythonTool()
        result = await tool.execute(code="print('hello from python')")
        assert result.success is True
        assert "hello from python" in result.output

    async def test_syntax_error(self):
        from src.tools.python_tool import PythonTool
        tool = PythonTool()
        valid, msg = await tool.validate_args(code="def broken(: pass")
        assert valid is False
        assert "Syntax error" in msg

    async def test_runtime_error(self):
        from src.tools.python_tool import PythonTool
        tool = PythonTool()
        result = await tool.execute(code="x = 1/0")
        assert result.success is False
        assert "Runtime error" in result.error

    async def test_dry_run(self):
        from src.tools.python_tool import PythonTool
        tool = PythonTool()
        result = await tool.execute(code="print('hello')", dry_run=True)
        assert result.success is True
        assert "dry-run" in result.output

    async def test_empty_code_invalid(self):
        from src.tools.python_tool import PythonTool
        tool = PythonTool()
        valid, msg = await tool.validate_args(code="   ")
        assert valid is False


# ─── WebSearchTool ────────────────────────────────────────────────────────────

class TestWebSearchTool:
    async def test_empty_query_invalid(self):
        from src.tools.web_search_tool import WebSearchTool
        tool = WebSearchTool()
        valid, msg = await tool.validate_args(query="")
        assert valid is False
        assert "query" in msg.lower()

    async def test_dry_run(self):
        from src.tools.web_search_tool import WebSearchTool
        tool = WebSearchTool()
        result = await tool.execute(query="test query", dry_run=True)
        assert result.success is True
        assert "dry-run" in result.output

    async def test_valid_query_valid(self):
        from src.tools.web_search_tool import WebSearchTool
        tool = WebSearchTool()
        valid, msg = await tool.validate_args(query="Python programming")
        assert valid is True


# ─── EmailTool ────────────────────────────────────────────────────────────────

class TestEmailTool:
    async def test_missing_to_field(self):
        from src.tools.email_tool import EmailTool
        tool = EmailTool()
        valid, msg = await tool.validate_args(to="", subject="Hi", body="Hello")
        assert valid is False

    async def test_missing_subject_field(self):
        from src.tools.email_tool import EmailTool
        tool = EmailTool()
        valid, msg = await tool.validate_args(to="a@b.com", subject="", body="Hello")
        assert valid is False

    async def test_invalid_email_address(self):
        from src.tools.email_tool import EmailTool
        tool = EmailTool()
        valid, msg = await tool.validate_args(to="notanemail", subject="Hi", body="Hello")
        assert valid is False
        assert "Invalid email" in msg

    async def test_dry_run(self):
        from src.tools.email_tool import EmailTool
        tool = EmailTool()
        result = await tool.execute(to="test@example.com", subject="Hi", body="Hello", dry_run=True)
        assert result.success is True
        assert "dry-run" in result.output
        assert "test@example.com" in result.output

    async def test_no_smtp_config_returns_error(self, monkeypatch):
        from src.tools.email_tool import EmailTool
        tool = EmailTool()
        monkeypatch.delenv("SMTP_HOST", raising=False)
        result = await tool.execute(to="test@example.com", subject="Hi", body="Hello")
        assert result.success is False
        assert "SMTP" in result.error


# ─── RAGTool ────────────────────────────────────────────────────────────────

class TestRAGTool:
    async def test_no_memory_manager_returns_error(self):
        from src.tools.rag_tool import RAGTool
        tool = RAGTool(memory_manager=None)
        result = await tool.execute(query="test query")
        assert result.success is False
        assert "Memory manager" in result.error

    async def test_dry_run(self):
        from src.tools.rag_tool import RAGTool
        tool = RAGTool(memory_manager=None)
        result = await tool.execute(query="test query", dry_run=True)
        assert result.success is True
        assert "dry-run" in result.output

    async def test_empty_query_invalid(self):
        from src.tools.rag_tool import RAGTool
        tool = RAGTool()
        valid, msg = await tool.validate_args(query="")
        assert valid is False

    async def test_with_memory_manager(self):
        from src.tools.rag_tool import RAGTool
        mock_memory = AsyncMock()
        mock_memory.search = AsyncMock(return_value="Found: insurance document")

        tool = RAGTool(memory_manager=mock_memory)
        result = await tool.execute(query="insurance")
        assert result.success is True
        assert "insurance" in result.output
