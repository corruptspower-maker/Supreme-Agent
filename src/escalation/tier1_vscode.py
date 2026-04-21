"""Tier 1 escalation – VS Code / Cline subprocess integration."""
from __future__ import annotations

import asyncio
import json
import os

from src.core.models import EscalationRequest, EscalationResponse, EscalationTier
from src.utils.logging import json_log

# Configurable via environment
_CLINE_EXEC = os.getenv("CLINE_EXECUTABLE", "cline")
_CLINE_TIMEOUT = float(os.getenv("CLINE_TIMEOUT_SECONDS", "120"))
# Use --act mode by default; set CLINE_PLAN_MODE=true to use --plan mode instead
_CLINE_PLAN_MODE = os.getenv("CLINE_PLAN_MODE", "false").lower() == "true"


def _build_prompt(request: EscalationRequest) -> str:
    """Build a concise single-line repair prompt for the Cline CLI positional argument."""
    ctx = request.context.replace("\n", " ").replace('"', "'")[:400]
    return (
        f"Fix failure in task {request.task_id} step {request.step_id}. "
        f"Reason: {request.reason.value}. Context: {ctx}. "
        "Reply with JSON: "
        '{\"action\":\"<retry|rewrite|skip|escalate>\",\"patch\":\"<fix>\",\"notes\":\"<why>\"}'
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
    """Invoke Tier-1 (VS Code / Cline) escalation via subprocess.

    Passes the prompt as a positional argument to the Cline CLI:
    ``cline [--act|--plan] --yolo -t <timeout> "<prompt>"``

    Args:
        request: The EscalationRequest describing the failure.

    Returns:
        EscalationResponse with the Cline-proposed solution.

    Raises:
        RuntimeError: If the Cline executable is not found or the subprocess fails.
    """
    json_log(
        "escalation_tier1_invoked",
        task_id=request.task_id,
        step_id=request.step_id,
        reason=request.reason.value,
    )

    prompt = _build_prompt(request)
    output = await _run_cline(prompt)
    solution = _extract_json(output)
    json_log("escalation_tier1_complete", task_id=request.task_id)

    return EscalationResponse(
        request_id=request.id,
        solution=solution,
        confidence=0.85,
        tier=EscalationTier.TIER1_VSCODE,
    )


async def _run_cline(prompt: str) -> str:
    """Run the Cline CLI with the prompt as a positional argument."""
    mode_flag = "--plan" if _CLINE_PLAN_MODE else "--act"
    args = [
        _CLINE_EXEC,
        mode_flag,
        "--yolo",
        "-t",
        str(int(_CLINE_TIMEOUT)),
        prompt,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=_CLINE_TIMEOUT + 5,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Cline timed out after {_CLINE_TIMEOUT}s")
    except FileNotFoundError:
        raise RuntimeError(
            f"Cline executable '{_CLINE_EXEC}' not found. "
            "Install via `npm install -g @cline-bot/cline` or set CLINE_EXECUTABLE."
        )

    if proc.returncode not in (0, None):
        err = stderr.decode(errors="replace").strip()
        raise RuntimeError(f"Cline exited {proc.returncode}: {err}")
    return stdout.decode(errors="replace").strip()
