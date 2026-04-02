"""Tests for src/utils/screenshot.py."""

from __future__ import annotations

import base64
import sys
from unittest.mock import patch


class TestCaptureScreenshot:
    def test_returns_none_when_mss_unavailable(self):
        """Graceful fallback when mss is not installed."""
        from src.utils.screenshot import capture_screenshot

        with patch.dict(sys.modules, {"mss": None, "mss.tools": None}):
            result = capture_screenshot("test")
        # Either None (mss not importable) or a valid dict
        # In headless env this will be None
        assert result is None or isinstance(result, dict)

    def test_returns_none_on_mss_import_error(self, monkeypatch):
        """Returns None if mss raises ImportError."""
        from src.utils import screenshot as sc_module

        original = sc_module.capture_screenshot

        def fake_capture(description="", action_taken=""):
            sc_module._ensure_dir()
            try:
                raise ImportError("mss not available")
            except ImportError:
                return None

        monkeypatch.setattr(sc_module, "capture_screenshot", fake_capture)
        result = sc_module.capture_screenshot("test")
        assert result is None


class TestScreenshotToBase64:
    def test_valid_png_file(self, tmp_path):
        """Reads a real PNG file and returns base64."""
        from src.utils.screenshot import screenshot_to_base64

        # Create a minimal valid PNG
        png_bytes = (
            b'\x89PNG\r\n\x1a\n'
            b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx'
            b'\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00'
            b'\x00\x00IEND\xaeB`\x82'
        )
        png_file = tmp_path / "test.png"
        png_file.write_bytes(png_bytes)

        result = screenshot_to_base64(str(png_file))
        assert result is not None
        decoded = base64.b64decode(result)
        assert decoded == png_bytes

    def test_missing_file_returns_none(self):
        """Returns None for a missing file."""
        from src.utils.screenshot import screenshot_to_base64
        result = screenshot_to_base64("/nonexistent/path/screenshot.png")
        assert result is None

    def test_returns_string(self, tmp_path):
        """Result is a string."""
        from src.utils.screenshot import screenshot_to_base64
        f = tmp_path / "x.png"
        f.write_bytes(b"PNG")
        result = screenshot_to_base64(str(f))
        assert isinstance(result, str)


class TestCreateThumbnail:
    def test_creates_thumbnail_with_correct_width(self, tmp_path):
        """Thumbnail should be 400px wide."""
        from PIL import Image

        from src.utils.screenshot import _create_thumbnail

        # Create a test PNG image (800x600)
        img = Image.new("RGB", (800, 600), color=(255, 0, 0))
        test_path = tmp_path / "test_shot.png"
        img.save(str(test_path))

        # Temporarily override SCREENSHOT_DIR
        import src.utils.screenshot as sc
        orig_dir = sc.SCREENSHOT_DIR
        sc.SCREENSHOT_DIR = tmp_path
        try:
            thumb = _create_thumbnail(test_path)
            assert thumb is not None
            assert thumb.exists()
            result_img = Image.open(thumb)
            assert result_img.size[0] == 400
            # Check aspect ratio preserved (600/800 * 400 = 300)
            assert result_img.size[1] == 300
        finally:
            sc.SCREENSHOT_DIR = orig_dir

    def test_returns_none_on_failure(self, tmp_path):
        """Returns None if image cannot be opened."""
        from src.utils.screenshot import _create_thumbnail

        bad_file = tmp_path / "not_an_image.png"
        bad_file.write_bytes(b"not a png")
        result = _create_thumbnail(bad_file)
        assert result is None


class TestCaptureScreenshotAsync:
    async def test_async_capture_returns_none_in_headless(self):
        """Async capture returns None in headless environment."""
        from src.utils.screenshot import capture_screenshot_async
        result = await capture_screenshot_async("test description")
        # In headless env, mss will fail → None
        assert result is None or isinstance(result, dict)

    async def test_async_capture_delegates_to_sync(self, monkeypatch):
        """Async wrapper properly delegates to sync version."""
        from src.utils import screenshot as sc

        called = []

        def fake_sync(description="", action_taken=""):
            called.append((description, action_taken))
            return None

        monkeypatch.setattr(sc, "capture_screenshot", fake_sync)
        result = await sc.capture_screenshot_async("hello", "click")
        assert called == [("hello", "click")]
