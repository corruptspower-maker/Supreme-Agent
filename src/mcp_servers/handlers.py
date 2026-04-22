"""MCP server request handlers."""

from __future__ import annotations

from loguru import logger


async def handle_list_tools(agent) -> dict:
    """Return only the single externally visible MCP tool."""
    tool_schema = {
        "name": "run_agent",
        "description": "Execute a task using Supreme Agent",
        "parameters": {
            "type": "object",
            "properties": {"goal": {"type": "string"}},
            "required": ["goal"],
        },
    }
    return {"tools": [tool_schema]}


async def handle_execute_tool(agent, tool_name: str, args: dict) -> dict:
    """Execute only run_agent for MCP clients (all other tools are internal)."""
    if agent is None:
        return {"success": False, "error": "Agent not available"}
    if tool_name != "run_agent":
        return {
            "success": False,
            "error_type": "UNKNOWN_TOOL",
            "stderr": f"{tool_name} not registered",
            "error": f"{tool_name} not registered",
        }

    try:
        goal = str(args.get("goal", "")).strip()
        if not goal:
            return {"success": False, "error": "goal is required"}
        result = await agent.run_async(goal, source="mcp")
        return {"success": result.get("status") == "completed", "output": result}
    except Exception as e:
        logger.error(f"MCP tool execution error: {e}")
        return {"success": False, "error": str(e)}


async def handle_get_status(agent) -> dict:
    """Return agent status."""
    if agent and hasattr(agent, "get_status"):
        return agent.get_status()
    return {"error": "Agent not available"}


async def handle_submit_task(agent, text: str, source: str = "mcp") -> dict:
    """Submit a task via MCP."""
    if agent is None:
        return {"success": False, "error": "Agent not available"}
    try:
        task = await agent.submit_request(text, source=source)
        return {"success": True, "task_id": task.id}
    except Exception as e:
        return {"success": False, "error": str(e)}
