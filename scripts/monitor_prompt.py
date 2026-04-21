"""Autonomous window monitor — screenshot → vision model → respond to prompts.

Runs a loop every N seconds:
  1. Focus the target window
  2. Capture a screenshot
  3. Ask the local vision model if the specified prompt text is visible
  4. If yes → send the configured key (default: Enter)
  5. Sleep and repeat

Usage::

    uv run scripts/monitor_prompt.py
    uv run scripts/monitor_prompt.py --window "PowerShell" --interval 60
    uv run scripts/monitor_prompt.py --window "PowerShell" --prompt-text "proceed" --key enter

Environment variables (override CLI defaults):
    LM_STUDIO_URL            LM Studio base URL (default: http://localhost:1234)
    LM_STUDIO_VISION_MODEL   Vision model name loaded in LM Studio
    LM_STUDIO_TIMEOUT        Vision API timeout in seconds (default: 120)

Requirements:
    pip install pygetwindow pyautogui
    A vision-capable model loaded in LM Studio (e.g. LLaVA, Qwen2-VL, llama-3.2-vision)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
import time
from io import BytesIO
from pathlib import Path

# ---------------------------------------------------------------------------
# Minimal inline implementations so this script runs standalone without the
# full src package on the Python path.  When run via `uv run` from the repo
# root, src IS on the path and the tools are imported normally below.
# ---------------------------------------------------------------------------


def _capture_screen_bytes() -> bytes:
    import mss
    from PIL import Image

    with mss.mss() as sct:
        monitor = sct.monitors[1]
        raw = sct.grab(monitor)
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _focus_window(title_pattern: str) -> str | None:
    """Return the matched window title, or None."""
    try:
        import pygetwindow as gw  # type: ignore[import]

        pattern_lower = title_pattern.lower()
        matches = [w for w in gw.getAllWindows() if pattern_lower in w.title.lower()]
        if matches:
            matches[0].activate()
            time.sleep(0.3)
            return matches[0].title
    except Exception as exc:
        print(f"[warn] focus_window: {exc}", file=sys.stderr)
    return None


def _press_key(key: str) -> None:
    try:
        import pyautogui  # type: ignore[import]

        pyautogui.FAILSAFE = True
        pyautogui.press(key)
    except Exception as exc:
        print(f"[warn] press_key: {exc}", file=sys.stderr)


async def _ask_vision(b64_image: str, prompt: str, lm_url: str, model: str, timeout: float) -> str:
    import httpx

    data_url = f"data:image/png;base64,{b64_image}"
    payload: dict = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0.0,
        "max_tokens": 2048,  # reasoning model needs room to think
    }
    if model:
        payload["model"] = model

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{lm_url}/v1/chat/completions", json=payload)
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        # Reasoning models put answer in "content"; fall back to "reasoning_content"
        return msg.get("content") or msg.get("reasoning_content") or ""


def _detect_with_ocr(img_bytes: bytes, search_text: str) -> bool:
    """Fallback: use pytesseract OCR if available."""
    try:
        import pytesseract  # type: ignore[import]
        from PIL import Image

        img = Image.open(BytesIO(img_bytes))
        text = pytesseract.image_to_string(img)
        return search_text.lower() in text.lower()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def monitor_loop(
    window: str,
    interval: int,
    prompt_text: str,
    response_key: str,
    lm_url: str,
    model: str,
    timeout: float,
    use_ocr_fallback: bool,
    dry_run: bool,
    verbose: bool,
) -> None:
    iteration = 0
    print(f"[monitor] Watching '{window}' every {interval}s — looking for: '{prompt_text}'")
    print(f"[monitor] Response key: '{response_key}' | dry_run={dry_run}")
    print("[monitor] Press Ctrl+C to stop.\n")

    while True:
        iteration += 1
        ts = time.strftime("%H:%M:%S")

        # 1. Focus window
        matched = _focus_window(window)
        if verbose:
            print(f"[{ts}] #{iteration} focused: {matched or '(not found)'}")

        # 2. Screenshot
        try:
            img_bytes = _capture_screen_bytes()
        except Exception as exc:
            print(f"[{ts}] screenshot failed: {exc}", file=sys.stderr)
            await asyncio.sleep(interval)
            continue

        b64 = base64.b64encode(img_bytes).decode()

        # 3. Detect prompt via vision model
        detected = False
        vision_ok = False

        vision_prompt = (
            f"Look at this terminal screenshot. "
            f"Is the text '{prompt_text}' visible anywhere, especially near the bottom? "
            "Answer with a single word: YES or NO."
        )

        try:
            answer = await _ask_vision(b64, vision_prompt, lm_url, model, timeout)
            vision_ok = True
            detected = "yes" in answer.strip().lower()
            if verbose:
                print(f"[{ts}] vision response: {answer.strip()!r}")
        except Exception as exc:
            if verbose:
                print(f"[{ts}] vision error: {exc}", file=sys.stderr)

        # 4. OCR fallback
        if not vision_ok and use_ocr_fallback:
            detected = _detect_with_ocr(img_bytes, prompt_text)
            if verbose:
                print(f"[{ts}] OCR fallback detected={detected}")

        # 5. Act
        if detected:
            print(f"[{ts}] ✅ Prompt detected — sending '{response_key}'")
            if not dry_run:
                _press_key(response_key)
        else:
            if verbose:
                print(f"[{ts}] No prompt detected.")

        await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Monitor a window and auto-respond to interactive prompts."
    )
    p.add_argument(
        "--window", "-w",
        default="PowerShell",
        help="Partial window title to watch (default: PowerShell)",
    )
    p.add_argument(
        "--interval", "-i",
        type=int,
        default=60,
        help="Seconds between checks (default: 60)",
    )
    p.add_argument(
        "--prompt-text", "-p",
        default="do you want to proceed",
        help="Text to look for in the window (default: 'do you want to proceed')",
    )
    p.add_argument(
        "--key", "-k",
        default="enter",
        help="Key to press when prompt is detected (default: enter)",
    )
    p.add_argument(
        "--lm-studio-url",
        default=os.getenv("LM_STUDIO_URL", "http://localhost:1234"),
        help="LM Studio base URL (default: http://localhost:1234)",
    )
    p.add_argument(
        "--model",
        default=os.getenv("LM_STUDIO_VISION_MODEL", ""),
        help="Vision model name in LM Studio",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("LM_STUDIO_TIMEOUT", "120")),
        help="Vision API timeout in seconds (default: 120)",
    )
    p.add_argument(
        "--ocr-fallback",
        action="store_true",
        help="Use pytesseract OCR when vision model is unavailable",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect prompts but do NOT press any keys",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print every iteration's details",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        asyncio.run(
            monitor_loop(
                window=args.window,
                interval=args.interval,
                prompt_text=args.prompt_text,
                response_key=args.key,
                lm_url=args.lm_studio_url,
                model=args.model,
                timeout=args.timeout,
                use_ocr_fallback=args.ocr_fallback,
                dry_run=args.dry_run,
                verbose=args.verbose,
            )
        )
    except KeyboardInterrupt:
        print("\n[monitor] Stopped.")


if __name__ == "__main__":
    main()
