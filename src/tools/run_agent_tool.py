"""Single MCP-facing tool that delegates execution to Supreme Agent."""

from __future__ import annotations

import time
from typing import Any

from src.core.models import RiskLevel
from src.tools.base import BaseTool


class RunAgentTool(BaseTool):
    """Delegates user goals to the ExecutiveAgent control loop."""

    name = "run_agent"
    description = "Execute a task using Supreme Agent"
    risk_level = RiskLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {"goal": {"type": "string"}},
        "required": ["goal"],
    }

    def __init__(self, agent=None) -> None:
        self._agent = agent

    async def validate_args(self, **kwargs: Any) -> tuple[bool, str]:
        goal = kwargs.get("goal", "")
        if not isinstance(goal, str) or not goal.strip():
            return False, "goal is required"
        return True, ""

    async def execute(self, **kwargs: Any):
        start = time.monotonic()
        goal = kwargs.get("goal", "")
        if self._agent is None:
            return self._timed_result(start, False, error="ExecutiveAgent not attached")
        result = await self._agent.run_async(goal, source="run_agent_tool")
        return self._timed_result(start, True, output=str(result))
