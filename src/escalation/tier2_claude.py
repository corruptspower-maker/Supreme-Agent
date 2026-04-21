"""Tier 2 escalation – Anthropic Claude API via httpx."""
from __future__ import annotations

import json
import os

import httpx

from src.core.models import EscalationRequest, EscalationResponse, EscalationTier
from src.utils.logging import json_log

_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022")
_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "4096"))
_TIMEOUT = float(os.getenv("CLAUDE_TIMEOUT_SECONDS", "60"))
_API_URL = "https://api.anthropic.com/v1/messages"

_SYSTEM_PROMPT = (
    "You are an expert debugging assistant for an autonomous AI agent. "
    "When given a failing task context, analyse the error and respond ONLY with a "
    "single-line JSON object:\n"
    '{"action": "<retry|rewrite|skip|escalate>", '
    '"patch": "<code or shell commands to apply>", '
    '"notes": "<brief explanation>", '
    '"confidence": <float 0.0-1.0>}'
)


def _build_messages(request: EscalationRequest) -> list[dict[str, str]]:
    user_content = (
        f"<system>\n{_SYSTEM_PROMPT}\n</system>\n\n"
        f"Task ID: {request.task_id}\n"
        f"Step ID: {request.step_id}\n"
        f"Failure reason: {request.reason.value}\n"
        f"Context:\n{request.context}"
    )
    return [{"role": "user", "content": user_content}]


def _parse_solution(text: str) -> tuple[str, float]:
    """Extract JSON solution and confidence score from the model's response."""
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        fragment = text[start:end]
        try:
            data = json.loads(fragment)
            confidence = float(data.get("confidence", 0.85))
            return fragment, min(max(confidence, 0.0), 1.0)
        except (json.JSONDecodeError, ValueError):
            pass
    return json.dumps({"action": "review", "patch": "", "notes": text[:2000]}), 0.5


async def run(request: EscalationRequest) -> EscalationResponse:
    """Invoke Tier-2 (Claude API) escalation via httpx.

    Reads the following environment variables:

    - ``ANTHROPIC_API_KEY`` (required)
    - ``CLAUDE_MODEL`` (default: ``claude-3-5-haiku-20241022``)
    - ``CLAUDE_MAX_TOKENS`` (default: ``4096``)
    - ``CLAUDE_TIMEOUT_SECONDS`` (default: ``60``)

    Args:
        request: The EscalationRequest describing the failure.

    Returns:
        EscalationResponse with Claude's proposed solution.

    Raises:
        RuntimeError: If ``ANTHROPIC_API_KEY`` is not set.
        httpx.HTTPStatusError: If the API returns a non-2xx response.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", _API_KEY)
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. "
            "Export it or add it to your .env file."
        )

    json_log(
        "escalation_tier2_invoked",
        task_id=request.task_id,
        step_id=request.step_id,
        reason=request.reason.value,
        model=_MODEL,
    )

    messages = _build_messages(request)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            _API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": _MODEL,
                "max_tokens": _MAX_TOKENS,
                "messages": messages,
            },
        )
        resp.raise_for_status()

    data = resp.json()
    raw_text: str = data["content"][0]["text"]
    solution, confidence = _parse_solution(raw_text)

    json_log(
        "escalation_tier2_complete",
        task_id=request.task_id,
        tokens_used=data.get("usage", {}).get("output_tokens", 0),
        model=_MODEL,
    )

    return EscalationResponse(
        request_id=request.id,
        solution=solution,
        confidence=confidence,
        tier=EscalationTier.TIER2_CLAUDE,
    )
