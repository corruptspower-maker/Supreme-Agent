"""Vision tool — send a screenshot to a local LM Studio vision model."""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any

import httpx

from src.core.models import RiskLevel, ToolResult
from src.tools.base import BaseTool

_DEFAULT_URL = "http://localhost:1234"
_DEFAULT_MODEL = ""  # LM Studio uses whichever model is currently loaded
_DEFAULT_TIMEOUT = 120.0


class VisionTool(BaseTool):
    """Ask a local vision-capable LLM (via LM Studio) about a screenshot.

    Sends the image as a base64 data-URL in the OpenAI-compatible messages API.

    Environment variables:
        LM_STUDIO_URL            Base URL for LM Studio (default: http://localhost:1234)
        LM_STUDIO_VISION_MODEL   Model name (default: whatever is loaded in LM Studio)
        LM_STUDIO_TIMEOUT        Request timeout in seconds (default: 120)
    """

    name = "vision_tool"
    description = (
        "Analyse a screenshot using the local LM Studio vision model. "
        "Pass the base64 PNG from screenshot_tool as 'image_b64', plus a text 'prompt'. "
        "Returns the model's text response."
    )
    risk_level = RiskLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "image_b64": {
                "type": "string",
                "description": "Base64-encoded PNG image (output of screenshot_tool).",
            },
            "image_path": {
                "type": "string",
                "description": "Alternatively, a file path to a PNG image.",
            },
            "prompt": {
                "type": "string",
                "description": "Question or instruction for the vision model.",
            },
            "model": {
                "type": "string",
                "description": "Override LM_STUDIO_VISION_MODEL for this call.",
            },
        },
        "required": ["prompt"],
    }

    async def validate_args(self, **kwargs: Any) -> tuple[bool, str]:
        if not kwargs.get("image_b64") and not kwargs.get("image_path"):
            return False, "Provide either image_b64 or image_path"
        if not kwargs.get("prompt"):
            return False, "prompt is required"
        return True, ""

    async def execute(self, **kwargs: Any) -> ToolResult:
        start = time.monotonic()

        image_b64: str | None = kwargs.get("image_b64")
        image_path: str | None = kwargs.get("image_path")
        prompt: str = kwargs["prompt"]
        model: str = kwargs.get("model") or os.getenv("LM_STUDIO_VISION_MODEL", _DEFAULT_MODEL)

        lm_url = os.getenv("LM_STUDIO_URL", _DEFAULT_URL).rstrip("/")
        timeout = float(os.getenv("LM_STUDIO_TIMEOUT", str(_DEFAULT_TIMEOUT)))

        # Resolve image bytes
        if image_b64:
            b64 = image_b64
        else:
            try:
                raw = Path(image_path).read_bytes()  # type: ignore[arg-type]
                b64 = base64.b64encode(raw).decode()
            except Exception as exc:
                return self._timed_result(start, False, error=f"Cannot read image: {exc}")

        data_url = f"data:image/png;base64,{b64}"

        payload: dict[str, Any] = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "temperature": 0.1,
            "max_tokens": 512,
        }
        if model:
            payload["model"] = model

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{lm_url}/v1/chat/completions",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError:
            return self._timed_result(
                start, False,
                error=f"Cannot connect to LM Studio at {lm_url}. Is it running?"
            )
        except Exception as exc:
            return self._timed_result(start, False, error=str(exc))

        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            return self._timed_result(start, False, error=f"Unexpected response shape: {exc}")

        return self._timed_result(start, True, output=answer)
