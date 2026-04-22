"""Tests for MCP single-tool exposure (run_agent only)."""

from __future__ import annotations

import pytest

from src.mcp_servers.handlers import handle_execute_tool, handle_list_tools


@pytest.mark.asyncio
async def test_handle_list_tools_only_run_agent():
    result = await handle_list_tools(agent=None)
    tools = result["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "run_agent"


@pytest.mark.asyncio
async def test_handle_execute_tool_blocks_non_run_agent():
    class DummyAgent:
        async def run_async(self, goal: str, source: str = "mcp"):
            return {"status": "completed"}

    result = await handle_execute_tool(DummyAgent(), "file_tool", {"action": "list", "path": "."})
    assert result["success"] is False
    assert result["error_type"] == "UNKNOWN_TOOL"
