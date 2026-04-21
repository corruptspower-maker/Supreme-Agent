"""Keyboard input tool — send keystrokes or text to the active window."""

from __future__ import annotations

import time
from typing import Any

from src.core.models import RiskLevel, ToolResult
from src.tools.base import BaseTool

# Map friendly names to pyautogui key strings
_KEY_ALIASES: dict[str, str] = {
    "enter": "enter",
    "return": "enter",
    "yes": "y",
    "no": "n",
    "escape": "escape",
    "esc": "escape",
    "space": "space",
    "tab": "tab",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
}


class KeyboardTool(BaseTool):
    """Send keyboard input (keypress, text, or hotkey) to the active window.

    DANGEROUS — always confirm before sending input to sensitive windows.
    """

    name = "keyboard_tool"
    description = (
        "Send keystrokes to the currently focused window. "
        "Actions: 'press' (single key), 'type' (text string), 'hotkey' (combo like ctrl+c). "
        "Params: action, keys (string or comma-separated list for hotkey)."
    )
    risk_level = RiskLevel.DANGEROUS
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["press", "type", "hotkey"],
                "description": (
                    "'press': press a single key (enter, y, n, escape, …). "
                    "'type': type a text string character by character. "
                    "'hotkey': send a key combination, e.g. 'ctrl+c'."
                ),
            },
            "keys": {
                "type": "string",
                "description": (
                    "For 'press': key name (enter, y, escape, …). "
                    "For 'type': text to type. "
                    "For 'hotkey': keys joined by '+' (ctrl+alt+del)."
                ),
            },
            "interval": {
                "type": "number",
                "description": "Seconds between keystrokes for 'type' (default 0.05).",
                "default": 0.05,
            },
        },
        "required": ["action", "keys"],
    }

    async def validate_args(self, **kwargs: Any) -> tuple[bool, str]:
        action = kwargs.get("action")
        if action not in ("press", "type", "hotkey"):
            return False, "action must be 'press', 'type', or 'hotkey'"
        if not kwargs.get("keys"):
            return False, "'keys' is required"
        return True, ""

    async def execute(self, **kwargs: Any) -> ToolResult:
        start = time.monotonic()
        action: str = kwargs["action"]
        keys: str = kwargs["keys"]
        interval: float = float(kwargs.get("interval", 0.05))

        try:
            import pyautogui  # type: ignore[import]
        except ImportError:
            return self._timed_result(
                start, False,
                error="pyautogui not installed. Run: uv add pyautogui"
            )

        pyautogui.FAILSAFE = True  # move mouse to top-left to abort

        try:
            if action == "press":
                key = _KEY_ALIASES.get(keys.lower(), keys.lower())
                pyautogui.press(key)
                return self._timed_result(start, True, output=f"Pressed: {key}")

            if action == "type":
                pyautogui.typewrite(keys, interval=interval)
                return self._timed_result(start, True, output=f"Typed: {keys!r}")

            # hotkey
            parts = [k.strip() for k in keys.replace("+", " ").split()]
            pyautogui.hotkey(*parts)
            return self._timed_result(start, True, output=f"Hotkey: {keys}")

        except Exception as exc:
            return self._timed_result(start, False, error=str(exc))
