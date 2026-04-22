#!/usr/bin/env python3
"""LM Studio MCP entrypoint exposing only `run_agent`."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.executive import ExecutiveAgent

mcp = FastMCP(name="Supreme-Agent Harness")

_agent: ExecutiveAgent | None = None
_agent_lock = asyncio.Lock()


async def _get_agent() -> ExecutiveAgent:
    global _agent
    async with _agent_lock:
        if _agent is None:
            _agent = ExecutiveAgent()
            await _agent.start()
        return _agent


@mcp.tool(
    name="run_agent",
    description="Execute a task using Supreme Agent",
)
async def run_agent(goal: str) -> dict:
    """Single externally visible tool: delegates execution to ExecutiveAgent."""
    if not goal or not goal.strip():
        return {"success": False, "error": "goal is required"}
    agent = await _get_agent()
    result = await agent.run_async(goal.strip(), source="lmstudio_mcp")
    return {"success": result.get("status") == "completed", "result": result}


if __name__ == "__main__":
    mcp.run()
