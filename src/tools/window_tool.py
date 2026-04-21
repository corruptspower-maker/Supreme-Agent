"""Window management tool — list and focus OS windows by title."""

from __future__ import annotations

import json
import time
from typing import Any

from src.core.models import RiskLevel, ToolResult
from src.tools.base import BaseTool


class WindowTool(BaseTool):
    """List open windows or bring a window to the foreground by title pattern."""

    name = "window_tool"
    description = (
        "List all open windows or focus a specific window by partial title match. "
        "Actions: 'list' (returns window titles), 'focus' (activates window). "
        "Param: action, title_pattern (required for focus)."
    )
    risk_level = RiskLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "focus"],
                "description": "'list' returns all window titles. 'focus' activates the first match.",
            },
            "title_pattern": {
                "type": "string",
                "description": "Partial window title to match (case-insensitive). Required for 'focus'.",
            },
        },
        "required": ["action"],
    }

    async def validate_args(self, **kwargs: Any) -> tuple[bool, str]:
        action = kwargs.get("action")
        if action not in ("list", "focus"):
            return False, "action must be 'list' or 'focus'"
        if action == "focus" and not kwargs.get("title_pattern"):
            return False, "title_pattern is required for action='focus'"
        return True, ""

    async def execute(self, **kwargs: Any) -> ToolResult:
        start = time.monotonic()
        action: str = kwargs["action"]
        pattern: str = kwargs.get("title_pattern", "")

        try:
            import pygetwindow as gw  # type: ignore[import]
        except ImportError:
            return self._timed_result(
                start, False,
                error="pygetwindow not installed. Run: uv add pygetwindow"
            )

        if action == "list":
            titles = [w.title for w in gw.getAllWindows() if w.title.strip()]
            return self._timed_result(start, True, output=json.dumps(titles))

        # action == "focus"
        pattern_lower = pattern.lower()
        matches = [w for w in gw.getAllWindows() if pattern_lower in w.title.lower()]
        if not matches:
            return self._timed_result(
                start, False,
                error=f"No window matching '{pattern}' found"
            )
        try:
            matches[0].activate()
            time.sleep(0.2)
        except Exception as exc:
            return self._timed_result(start, False, error=f"Activate failed: {exc}")

        return self._timed_result(start, True, output=f"Focused: {matches[0].title}")
