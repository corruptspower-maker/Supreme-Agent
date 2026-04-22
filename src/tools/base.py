"""Base tool interface for all Executive Agent tools."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from src.core.models import RiskLevel, ToolResult


class BaseTool(ABC):
    """Abstract base class for all agent tools."""

    name: str = ""
    description: str = ""
    risk_level: RiskLevel = RiskLevel.SAFE
    parameters_schema: dict = {}
    capabilities: list[str] = []
    """Capability tags used by the planner to find alternative tools.

    Examples: ["file_read", "file_write", "shell_exec", "web_search"]
    """

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with given arguments."""
        ...

    @abstractmethod
    async def validate_args(self, **kwargs: Any) -> tuple[bool, str]:
        """Validate arguments before execution. Returns (valid, error_message)."""
        ...

    def to_prompt_description(self) -> str:
        """Return a human-readable description for inclusion in LLM prompts."""
        return f"{self.name}: {self.description} (risk: {self.risk_level.value})"

    def to_mcp_schema(self) -> dict:
        """Return MCP-compatible JSON schema for this tool."""
        return {
            "name": self.name,
            "description": self.description,
            "risk_level": self.risk_level.value,
            "parameters": self.parameters_schema,
        }

    def _timed_result(
        self,
        start_ms: float,
        success: bool,
        output: str | None = None,
        error: str | None = None,
        side_effects: list[str] | None = None,
    ) -> ToolResult:
        """Build a ToolResult with execution time populated."""
        elapsed = int((time.monotonic() - start_ms) * 1000)
        return ToolResult(
            tool_name=self.name,
            success=success,
            output=output,
            error=error,
            execution_time_ms=elapsed,
            side_effects=side_effects or [],
        )
