"""Screenshot capture utility using mss."""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

SCREENSHOT_DIR = Path("data/screenshots")


def _ensure_dir() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def capture_screenshot(description: str = "", action_taken: str = "") -> Optional[dict]:
    """
    Capture a screenshot synchronously using mss.
    
    Returns dict with: id, image_path, description, timestamp, action_taken, thumbnail_path
    Falls back gracefully if mss is not available (headless env).
    """
    _ensure_dir()
    from src.core.models import ScreenshotEntry
    try:
        import mss
        import mss.tools
        with mss.mss() as sct:
            monitor = sct.monitors[0]
            sct_img = sct.grab(monitor)
            ts = datetime.utcnow()
            filename = f"screenshot_{ts.strftime('%Y%m%d_%H%M%S_%f')}.png"
            path = SCREENSHOT_DIR / filename
            mss.tools.to_png(sct_img.rgb, sct_img.size, output=str(path))
            thumb_path = _create_thumbnail(path)
            entry = ScreenshotEntry(
                image_path=str(path),
                description=description or "Screenshot captured",
                timestamp=ts,
                action_taken=action_taken or None,
            )
            logger.debug(f"Screenshot saved: {path}")
            return {
                "entry": entry,
                "thumbnail_path": str(thumb_path) if thumb_path else None,
            }
    except ImportError:
        logger.warning("mss not available — screenshot skipped")
        return None
    except Exception as e:
        logger.warning(f"Screenshot failed: {e}")
        return None


def _create_thumbnail(path: Path) -> Optional[Path]:
    """Create 400px-wide thumbnail using Pillow."""
    try:
        from PIL import Image
        thumb_dir = SCREENSHOT_DIR / "thumbnails"
        thumb_dir.mkdir(exist_ok=True)
        img = Image.open(path)
        w, h = img.size
        new_w = 400
        new_h = int(h * (new_w / w))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        thumb_path = thumb_dir / path.name
        img.save(str(thumb_path))
        return thumb_path
    except Exception as e:
        logger.warning(f"Thumbnail creation failed: {e}")
        return None


def screenshot_to_base64(path: str) -> Optional[str]:
    """Read a screenshot file and return base64-encoded PNG."""
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except OSError as e:
        logger.warning(f"Failed to read screenshot {path}: {e}")
        return None


async def capture_screenshot_async(description: str = "", action_taken: str = "") -> Optional[dict]:
    """Async wrapper for screenshot capture — runs in thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, capture_screenshot, description, action_taken)
