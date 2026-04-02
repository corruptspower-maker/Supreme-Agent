"""MCP server request handlers."""

from __future__ import annotations

from loguru import logger


async def handle_list_tools(agent) -> dict:
    """Return list of available tools."""
    tools = []
    if agent and hasattr(agent, "_registry"):
        for name, tool in agent._registry.items():
            tools.append(tool.to_mcp_schema())
    return {"tools": tools}


async def handle_execute_tool(agent, tool_name: str, args: dict) -> dict:
    """Execute a tool on behalf of an MCP client."""
    if agent is None:
        return {"success": False, "error": "Agent not available"}

    try:
        from src.core.models import PlanStep
        step = PlanStep(description=f"MCP call: {tool_name}", tool_name=tool_name, tool_args=args)

        if hasattr(agent, "_executor") and agent._executor:
            result = await agent._executor._router.route(step)
        else:
            return {"success": False, "error": "Executor not initialized"}

        return {"success": result.success, "output": result.output, "error": result.error}
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
