"""Monitor tool — launch the autonomous prompt-detection loop as a background task.

The agent can call this tool with a natural-language instruction like:
  "watch PowerShell and press Enter when it asks to proceed"

The tool starts the monitor_prompt.py loop in a background asyncio task (or subprocess
for long-running sessions) and returns immediately with a monitor ID the agent can use
to stop it later.
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
import time
from io import BytesIO
from typing import Any

from loguru import logger

from src.core.models import RiskLevel, ToolResult
from src.tools.base import BaseTool

_DEFAULT_MODEL = "omnicoder-qwen3.5-9b-claude-4.6-opus-uncensored-v2"
_active_monitors: dict[str, asyncio.Task] = {}  # monitor_id -> asyncio Task


class MonitorTool(BaseTool):
    """Start or stop an autonomous window-monitoring loop.

    The loop:
      1. Focuses the target window
      2. Takes a screenshot
      3. Asks the local vision model if the specified prompt text is visible
      4. If yes → sends the configured key (default: Enter)
      5. Waits `interval` seconds and repeats

    Actions:
      start  — begin monitoring (returns a monitor_id)
      stop   — stop monitoring (requires monitor_id)
      list   — list active monitors
      once   — run a single check right now (returns YES/NO + model answer)
    """

    name = "monitor_tool"
    description = (
        "Start, stop, or run an autonomous loop that watches a window for a text prompt "
        "and responds with a keypress. "
        "Use action='start' with window, prompt_text, key, interval. "
        "Use action='stop' with monitor_id to cancel. "
        "Use action='once' to do a single check immediately."
    )
    risk_level = RiskLevel.MODERATE
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "stop", "list", "once"],
                "description": "What to do: start/stop/list monitors, or run once.",
            },
            "window": {
                "type": "string",
                "description": "Partial window title to watch (default: PowerShell).",
            },
            "prompt_text": {
                "type": "string",
                "description": "Text to look for on screen (default: 'do you want to proceed').",
            },
            "key": {
                "type": "string",
                "description": "Key to press when prompt is detected (default: enter).",
            },
            "interval": {
                "type": "integer",
                "description": "Seconds between checks (default: 60).",
            },
            "monitor_id": {
                "type": "string",
                "description": "ID returned by start action; used to stop a monitor.",
            },
            "dry_run": {
                "type": "boolean",
                "description": "If true, detect but do NOT press any keys (default: false).",
            },
        },
        "required": ["action"],
    }

    async def validate_args(self, **kwargs: Any) -> tuple[bool, str]:
        action = kwargs.get("action")
        if action not in ("start", "stop", "list", "once"):
            return False, "action must be one of: start, stop, list, once"
        if action == "stop" and not kwargs.get("monitor_id"):
            return False, "monitor_id required for action='stop'"
        return True, ""

    async def execute(self, **kwargs: Any) -> ToolResult:
        start = time.monotonic()
        action: str = kwargs["action"]

        if action == "list":
            ids = list(_active_monitors.keys())
            return self._timed_result(
                start, True,
                output=f"Active monitors: {ids}" if ids else "No active monitors."
            )

        if action == "stop":
            mid = kwargs["monitor_id"]
            task = _active_monitors.pop(mid, None)
            if task:
                task.cancel()
                return self._timed_result(start, True, output=f"Monitor {mid} stopped.")
            return self._timed_result(start, False, error=f"No monitor with id={mid}")

        # Shared params for start / once
        window: str = kwargs.get("window", "PowerShell")
        prompt_text: str = kwargs.get("prompt_text", "do you want to proceed")
        key: str = kwargs.get("key", "enter")
        interval: int = int(kwargs.get("interval", 60))
        dry_run: bool = bool(kwargs.get("dry_run", False))

        if action == "once":
            detected, answer = await _single_check(window, prompt_text)
            if detected and not dry_run:
                _press(key)
                return self._timed_result(
                    start, True,
                    output=f"Prompt detected — pressed '{key}'. Model said: {answer}"
                )
            return self._timed_result(
                start, True,
                output=f"No prompt detected. Model said: {answer}"
            )

        # action == "start"
        import uuid
        mid = uuid.uuid4().hex[:8]

        async def _loop() -> None:
            logger.info(f"[monitor:{mid}] starting — window={window!r} prompt={prompt_text!r}")
            while True:
                try:
                    detected, answer = await _single_check(window, prompt_text)
                    if detected:
                        logger.info(f"[monitor:{mid}] prompt detected → pressing {key!r}")
                        if not dry_run:
                            _press(key)
                    else:
                        logger.debug(f"[monitor:{mid}] no prompt. model: {answer[:80]}")
                except asyncio.CancelledError:
                    logger.info(f"[monitor:{mid}] stopped.")
                    return
                except Exception as exc:
                    logger.warning(f"[monitor:{mid}] check error: {exc}")
                await asyncio.sleep(interval)

        t = asyncio.create_task(_loop())
        _active_monitors[mid] = t
        return self._timed_result(
            start, True,
            output=(
                f"Monitor started (id={mid}). Watching '{window}' every {interval}s "
                f"for '{prompt_text}'. Will press '{key}' when detected. "
                f"dry_run={dry_run}. Use action='stop' with monitor_id='{mid}' to cancel."
            )
        )


# ---------------------------------------------------------------------------
# Helpers (inline so this tool is self-contained)
# ---------------------------------------------------------------------------

async def _single_check(window: str, prompt_text: str) -> tuple[bool, str]:
    """Focus window, screenshot, ask vision model. Returns (detected, model_answer)."""
    _focus(window)
    await asyncio.sleep(0.3)

    b64 = await asyncio.get_event_loop().run_in_executor(None, _screenshot_b64)

    vision_prompt = (
        f"Look at this terminal/window screenshot. "
        f"Is the text '{prompt_text}' visible anywhere, especially near the bottom? "
        "Answer with a single word: YES or NO."
    )
    answer = await _ask_vision(b64, vision_prompt)
    detected = "yes" in answer.strip().lower()
    return detected, answer


def _focus(title_pattern: str) -> None:
    try:
        import pygetwindow as gw  # type: ignore[import]
        matches = [w for w in gw.getAllWindows() if title_pattern.lower() in w.title.lower()]
        if matches:
            matches[0].activate()
    except Exception as exc:
        logger.debug(f"focus: {exc}")


def _screenshot_b64() -> str:
    import mss
    from PIL import Image

    with mss.mss() as sct:
        raw = sct.grab(sct.monitors[1])
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    img.thumbnail((1280, 1280), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


async def _ask_vision(b64: str, prompt: str) -> str:
    import httpx

    model = os.getenv("LM_STUDIO_VISION_MODEL", _DEFAULT_MODEL)
    lm_url = os.getenv("LM_STUDIO_URL", "http://localhost:1234").rstrip("/")
    timeout = float(os.getenv("LM_STUDIO_TIMEOUT", "120"))

    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
        "temperature": 0.0,
        "max_tokens": 2048,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{lm_url}/v1/chat/completions", json=payload)
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        return msg.get("content") or msg.get("reasoning_content") or "(empty)"


def _press(key: str) -> None:
    try:
        import pyautogui  # type: ignore[import]
        pyautogui.FAILSAFE = True
        pyautogui.press(key)
    except Exception as exc:
        logger.warning(f"press key: {exc}")
