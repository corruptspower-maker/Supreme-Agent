"""Screenshot tool — capture full screen or a specific window."""

from __future__ import annotations

import base64
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import mss
from PIL import Image

from src.core.models import RiskLevel, ToolResult
from src.tools.base import BaseTool


class ScreenshotTool(BaseTool):
    """Capture a screenshot of the full desktop or a specific window by title.

    Returns the image as a base64-encoded PNG string (suitable for passing to a
    vision model) or saves it to a file.
    """

    name = "screenshot_tool"
    description = (
        "Capture a screenshot of the desktop or a named window. "
        "Returns base64 PNG or saves to a file. "
        "Params: window_title (optional), output_format ('base64'|'file'), output_path (optional)."
    )
    risk_level = RiskLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "window_title": {
                "type": "string",
                "description": "Partial window title to focus before capturing. "
                               "If omitted, the full primary monitor is captured.",
            },
            "output_format": {
                "type": "string",
                "enum": ["base64", "file"],
                "default": "base64",
                "description": "Return base64 string or save to file.",
            },
            "output_path": {
                "type": "string",
                "description": "File path when output_format='file'. "
                               "Defaults to screenshot_<timestamp>.png in cwd.",
            },
        },
    }

    async def validate_args(self, **kwargs: Any) -> tuple[bool, str]:
        fmt = kwargs.get("output_format", "base64")
        if fmt not in ("base64", "file"):
            return False, "output_format must be 'base64' or 'file'"
        return True, ""

    async def execute(self, **kwargs: Any) -> ToolResult:
        start = time.monotonic()
        window_title: str | None = kwargs.get("window_title")
        output_format: str = kwargs.get("output_format", "base64")
        output_path: str | None = kwargs.get("output_path")

        # Optionally focus the target window first
        if window_title:
            _try_focus(window_title)
            time.sleep(0.3)  # let the window paint

        try:
            img_bytes = _capture_screen()
        except Exception as exc:
            return self._timed_result(start, False, error=f"Capture failed: {exc}")

        if output_format == "file":
            dest = Path(output_path) if output_path else Path(f"screenshot_{int(time.time())}.png")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(img_bytes)
            return self._timed_result(start, True, output=str(dest))

        b64 = base64.b64encode(img_bytes).decode()
        return self._timed_result(start, True, output=b64)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _capture_screen() -> bytes:
    """Capture primary monitor and return raw PNG bytes."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # monitors[0] is the virtual "all" monitor
        raw = sct.grab(monitor)
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _try_focus(title_pattern: str) -> bool:
    """Best-effort: bring a window matching *title_pattern* to the foreground."""
    try:
        import pygetwindow as gw  # type: ignore[import]
        matches = gw.getWindowsWithTitle(title_pattern)
        if matches:
            matches[0].activate()
            return True
    except Exception:
        pass
    return False
