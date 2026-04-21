"""Tier 3 escalation – Playwright browser automation."""
from __future__ import annotations

import json
import os

from playwright.async_api import async_playwright

from src.core.models import EscalationRequest, EscalationResponse, EscalationTier
from src.utils.logging import json_log

# Target AI web UI (defaults to Claude.ai new conversation)
_TARGET_URL = os.getenv("TIER3_TARGET_URL", "https://claude.ai/new")
_HEADLESS = os.getenv("TIER3_HEADLESS", "true").lower() == "true"
_CHROME_PROFILE_DIR = os.getenv("CHROME_PROFILE_DIR", "")

# Timeouts in milliseconds
_BROWSER_TIMEOUT_MS = int(os.getenv("TIER3_BROWSER_TIMEOUT_MS", "60000"))
_RESPONSE_TIMEOUT_MS = int(os.getenv("TIER3_RESPONSE_TIMEOUT_MS", "120000"))

# CSS selectors – configurable for different AI web UIs (defaults target claude.ai)
_INPUT_SELECTOR = os.getenv("TIER3_INPUT_SELECTOR", 'div[contenteditable="true"]')
_SEND_SELECTOR = os.getenv("TIER3_SEND_SELECTOR", 'button[aria-label*="Send"]')
_RESPONSE_SELECTOR = os.getenv(
    "TIER3_RESPONSE_SELECTOR", '[data-testid="assistant-message"]'
)
_STOP_SELECTOR = os.getenv("TIER3_STOP_SELECTOR", 'button[aria-label*="Stop"]')


def _build_prompt(request: EscalationRequest) -> str:
    """Build a prompt suitable for submission to an AI web UI."""
    return (
        "I need help fixing an AI agent failure. "
        "Please respond with ONLY a JSON object on a single line.\n\n"
        f"Task ID: {request.task_id}\n"
        f"Step ID: {request.step_id}\n"
        f"Failure reason: {request.reason.value}\n"
        f"Context:\n{request.context}\n\n"
        'Required format: {"action": "<retry|rewrite|skip>", '
        '"patch": "<code or commands>", '
        '"notes": "<brief explanation>"}'
    )


def _extract_json(text: str) -> str:
    """Extract the first JSON object from text; fall back to wrapping as notes."""
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        fragment = text[start:end]
        try:
            json.loads(fragment)
            return fragment
        except json.JSONDecodeError:
            pass
    return json.dumps({"action": "review", "patch": "", "notes": text[:2000]})


async def run(request: EscalationRequest) -> EscalationResponse:
    """Invoke Tier-3 escalation via Playwright browser automation.

    Configure via environment variables:

    - ``TIER3_TARGET_URL`` – AI web UI URL (default: ``https://claude.ai/new``)
    - ``TIER3_HEADLESS`` – Run headless (default: ``true``)
    - ``CHROME_PROFILE_DIR`` – Path to persistent Chrome profile for auth sessions
    - ``TIER3_BROWSER_TIMEOUT_MS`` – Navigation timeout ms (default: ``60000``)
    - ``TIER3_RESPONSE_TIMEOUT_MS`` – Wait for AI response ms (default: ``120000``)

    Args:
        request: The EscalationRequest describing the failure.

    Returns:
        EscalationResponse with the extracted solution.
    """
    json_log(
        "escalation_tier3_invoked",
        task_id=request.task_id,
        step_id=request.step_id,
        reason=request.reason.value,
        target_url=_TARGET_URL,
    )

    prompt = _build_prompt(request)
    raw_text = await _browser_session(prompt)
    solution = _extract_json(raw_text)

    json_log(
        "escalation_tier3_complete",
        task_id=request.task_id,
        response_chars=len(raw_text),
    )

    return EscalationResponse(
        request_id=request.id,
        solution=solution,
        confidence=0.75,
        tier=EscalationTier.TIER3_BROWSER,
    )


async def _browser_session(prompt: str) -> str:
    """Open a browser, submit the prompt, and return the extracted response text."""
    async with async_playwright() as pw:
        if _CHROME_PROFILE_DIR:
            context = await pw.chromium.launch_persistent_context(
                _CHROME_PROFILE_DIR,
                headless=_HEADLESS,
                args=["--no-sandbox"],
                timeout=_BROWSER_TIMEOUT_MS,
            )
            page = await context.new_page()
            browser = None
        else:
            browser = await pw.chromium.launch(
                headless=_HEADLESS,
                args=["--no-sandbox"],
            )
            context = await browser.new_context()
            page = await context.new_page()

        try:
            page.set_default_timeout(_BROWSER_TIMEOUT_MS)
            await page.goto(_TARGET_URL, wait_until="networkidle")

            input_el = page.locator(_INPUT_SELECTOR).first
            await input_el.wait_for(state="visible")
            await input_el.click()
            await input_el.fill(prompt)

            try:
                send_btn = page.locator(_SEND_SELECTOR).first
                await send_btn.wait_for(state="visible", timeout=3000)
                await send_btn.click()
            except Exception:
                await page.keyboard.press("Enter")

            try:
                await page.locator(_STOP_SELECTOR).wait_for(
                    state="visible", timeout=10_000
                )
                await page.locator(_STOP_SELECTOR).wait_for(
                    state="hidden", timeout=_RESPONSE_TIMEOUT_MS
                )
            except Exception:
                await page.locator(_RESPONSE_SELECTOR).last.wait_for(
                    state="visible", timeout=_RESPONSE_TIMEOUT_MS
                )

            response_els = page.locator(_RESPONSE_SELECTOR)
            count = await response_els.count()
            raw_text = await response_els.last.inner_text() if count > 0 else ""
        finally:
            await context.close()
            if browser is not None:
                await browser.close()

    return raw_text.strip()
