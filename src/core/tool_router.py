"""Routes tool execution requests to the appropriate tool."""

from __future__ import annotations

from loguru import logger
from src.core.models import PlanStep, ToolResult


class ToolRouter:
    """Routes plan steps to registered tools."""

    def __init__(self, registry) -> None:
        self._registry = registry

    async def route(self, step: PlanStep) -> ToolResult:
        """Route a step to its tool and execute it."""
        if not step.tool_name:
            return ToolResult(
                tool_name="none",
                success=False,
                error="Step has no tool_name",
            )
        
        tool = self._registry.get(step.tool_name)
        if tool is None:
            logger.error(f"Tool not found: {step.tool_name}")
            return ToolResult(
                tool_name=step.tool_name,
                success=False,
                error=f"Tool '{step.tool_name}' not registered",
            )
        
        valid, msg = await tool.validate_args(**step.tool_args)
        if not valid:
            return ToolResult(
                tool_name=step.tool_name,
                success=False,
                error=f"Invalid args: {msg}",
            )
        
        logger.info(f"Routing to tool: {step.tool_name}")
        return await tool.execute(**step.tool_args)
