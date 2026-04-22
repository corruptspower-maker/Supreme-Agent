"""Tool registry — auto-discovery and runtime registration."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Optional

from loguru import logger

from src.tools.base import BaseTool


class ToolRegistry:
    """Registry for all available agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._stats: dict[str, dict] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        if not tool.name:
            raise ValueError(f"Tool {type(tool).__name__} has no name")
        self._tools[tool.name] = tool
        self._stats[tool.name] = {"calls": 0, "successes": 0, "failures": 0}
        logger.debug(f"Registered tool: {tool.name}")

    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def record_result(self, tool_name: str, success: bool) -> None:
        """Record a tool execution result for stats."""
        if tool_name in self._stats:
            self._stats[tool_name]["calls"] += 1
            if success:
                self._stats[tool_name]["successes"] += 1
            else:
                self._stats[tool_name]["failures"] += 1

    def get_stats(self) -> dict[str, dict]:
        """Return usage statistics per tool."""
        return dict(self._stats)

    def get_capable_tools(self, capability: str) -> list[BaseTool]:
        """Return all tools that have the given capability tag."""
        return [t for t in self._tools.values() if capability in (t.capabilities or [])]

    def list_tool_schemas(self) -> list[dict]:
        """Return MCP-compatible schemas for all registered tools (for LLM prompt injection)."""
        return [t.to_mcp_schema() for t in self._tools.values()]

    def autodiscover(self, tools_dir: Optional[Path] = None) -> int:
        """Auto-discover and register tools from the tools directory."""
        if tools_dir is None:
            tools_dir = Path(__file__).parent

        count = 0
        for py_file in tools_dir.glob("*_tool.py"):
            module_name = f"src.tools.{py_file.stem}"
            try:
                mod = importlib.import_module(module_name)
                for _, cls in inspect.getmembers(mod, inspect.isclass):
                    if (
                        issubclass(cls, BaseTool)
                        and cls is not BaseTool
                        and cls.name
                    ):
                        try:
                            self.register(cls())
                            count += 1
                        except Exception as e:
                            logger.warning(f"Failed to register {cls.__name__}: {e}")
            except ImportError as e:
                logger.warning(f"Failed to import {module_name}: {e}")

        logger.info(f"Auto-discovered {count} tools from {tools_dir}")
        return count

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
