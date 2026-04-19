"""Escalation manager — multi-tier escalation with circuit breaker."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

from loguru import logger

from src.core.models import (
    EscalationReason,
    EscalationRequest,
    EscalationResponse,
    EscalationTier,
    Task,
)
from src.utils.config import load_config


class _CircuitBreaker:
    """Simple per-tier circuit breaker.

    Opens after `failure_threshold` consecutive failures and stays open
    for `recovery_timeout_seconds` before allowing a retry.
    """

    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 300) -> None:
        self._threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failures = 0
        self._opened_at: Optional[float] = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.time() - self._opened_at >= self._recovery_timeout:
            # Half-open: allow one attempt
            self._opened_at = None
            self._failures = 0
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = time.time()
            logger.warning(
                f"Circuit breaker opened after {self._failures} consecutive failures"
            )


class EscalationManager:
    """Orchestrates escalation through up to three tiers.

    Tier 1 — GitHub Copilot API (fast, code-focused)
    Tier 2 — Claude Code CLI (subprocess, richer reasoning)
    Tier 3 — Cline via VS Code (interactive, last resort)

    Each tier has an independent circuit breaker.  The fallback chain is
    configurable via escalation.yaml.
    """

    def __init__(self) -> None:
        esc_cfg = load_config("escalation").get("escalation", {})
        models_cfg = load_config("models").get("escalation", {})

        triggers = esc_cfg.get("triggers", {})
        self._max_retries: int = int(triggers.get("max_retries_before_escalate", 3))
        self._min_confidence: float = float(triggers.get("min_confidence_threshold", 0.4))
        self._routing: dict[str, str] = esc_cfg.get("routing", {})
        self._fallback_chain: list[str] = esc_cfg.get(
            "fallback_chain", ["tier1", "tier2", "tier3"]
        )

        cb_cfg = esc_cfg.get("circuit_breaker", {})
        cb_threshold: int = int(cb_cfg.get("failure_threshold", 3))
        cb_recovery: float = float(cb_cfg.get("recovery_timeout_seconds", 300))

        self._breakers: dict[str, _CircuitBreaker] = {
            "tier1": _CircuitBreaker(cb_threshold, cb_recovery),
            "tier2": _CircuitBreaker(cb_threshold, cb_recovery),
            "tier3": _CircuitBreaker(cb_threshold, cb_recovery),
        }

        tier1_cfg = models_cfg.get("tier1", {})
        self._tier1_base_url: str = tier1_cfg.get("base_url", "https://api.githubcopilot.com")
        self._tier1_model: str = tier1_cfg.get("model", "gpt-4o")
        self._tier1_timeout: float = float(tier1_cfg.get("timeout_seconds", 30))

        tier2_cfg = models_cfg.get("tier2", {})
        self._tier2_command: str = tier2_cfg.get("command", "claude")
        self._tier2_flags: list[str] = tier2_cfg.get(
            "flags", ["--print", "--output-format", "json", "--max-turns", "10"]
        )
        self._tier2_timeout: float = float(tier2_cfg.get("timeout_seconds", 300))

        tier3_cfg = models_cfg.get("tier3", {})
        self._tier3_command: str = tier3_cfg.get("command", "claude")
        self._tier3_timeout: float = float(tier3_cfg.get("timeout_seconds", 600))

    # ─── Main entry point ─────────────────────────────────────────────────────

    async def escalate(
        self,
        task: Task,
        reason: EscalationReason,
        errors: Optional[list[str]] = None,
    ) -> Optional[EscalationResponse]:
        """Attempt escalation through the configured fallback chain.

        Returns the first successful EscalationResponse, or None if all
        tiers are exhausted.
        """
        request = EscalationRequest(
            reason=reason,
            tier=EscalationTier.TIER1_COPILOT,
            task_description=task.request.text,
            steps_attempted=task.plan.steps if task.plan else [],
            errors_encountered=errors or [],
        )

        for tier_key in self._fallback_chain:
            breaker = self._breakers.get(tier_key)
            if breaker and breaker.is_open:
                logger.warning(f"Escalation {tier_key} circuit breaker is open — skipping")
                continue

            logger.info(f"Escalating to {tier_key}: {reason.value}")
            try:
                response = await self._call_tier(tier_key, request, task)
                if response is not None:
                    if breaker:
                        breaker.record_success()
                    return response
            except Exception as e:
                logger.error(f"Escalation {tier_key} raised exception: {e}")
                if breaker:
                    breaker.record_failure()

        logger.error("All escalation tiers exhausted")
        return None

    async def _call_tier(
        self,
        tier_key: str,
        request: EscalationRequest,
        task: Task,
    ) -> Optional[EscalationResponse]:
        if tier_key == "tier1":
            return await self._call_tier1(request, task)
        elif tier_key == "tier2":
            return await self._call_tier2(request, task)
        elif tier_key == "tier3":
            return await self._call_tier3(request, task)
        return None

    # ─── Tier 1: GitHub Copilot API ───────────────────────────────────────────

    async def _call_tier1(
        self, request: EscalationRequest, task: Task
    ) -> Optional[EscalationResponse]:
        """Call the GitHub Copilot chat completion API."""
        import os

        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("COPILOT_TOKEN")
        if not token:
            logger.warning("Tier1: GITHUB_TOKEN / COPILOT_TOKEN not set — skipping")
            return None

        try:
            import httpx

            prompt = self._build_escalation_prompt(request)
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Copilot-Integration-Id": "executive-agent",
            }
            payload = {
                "model": self._tier1_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an expert software engineer helping to resolve a "
                            "failed autonomous agent task. Provide a concise solution."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 2048,
            }

            async with httpx.AsyncClient(timeout=self._tier1_timeout) as client:
                resp = await client.post(
                    f"{self._tier1_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            solution = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "No solution returned")
            )
            return EscalationResponse(
                request_id=request.id,
                tier_used=EscalationTier.TIER1_COPILOT,
                tool_used="copilot_api",
                solution=solution,
                confidence=0.75,
            )

        except Exception as e:
            logger.warning(f"Tier1 (Copilot API) failed: {e}")
            self._breakers["tier1"].record_failure()
            return None

    # ─── Tier 2: Claude Code CLI ──────────────────────────────────────────────

    async def _call_tier2(
        self, request: EscalationRequest, task: Task
    ) -> Optional[EscalationResponse]:
        """Invoke the Claude Code CLI via subprocess."""
        prompt = self._build_escalation_prompt(request)
        cmd = [self._tier2_command] + self._tier2_flags + [prompt]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self._tier2_timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                logger.warning("Tier2 (Claude Code CLI) timed out")
                self._breakers["tier2"].record_failure()
                return None

            if proc.returncode != 0:
                logger.warning(
                    f"Tier2 CLI exited {proc.returncode}: {stderr.decode()[:200]}"
                )
                self._breakers["tier2"].record_failure()
                return None

            raw = stdout.decode("utf-8", errors="replace")
            # Try to parse JSON output
            try:
                data = json.loads(raw)
                solution = data.get("result") or data.get("content") or raw
            except json.JSONDecodeError:
                solution = raw

            return EscalationResponse(
                request_id=request.id,
                tier_used=EscalationTier.TIER2_CLAUDE_CODE,
                tool_used="claude_code_cli",
                solution=solution[:4096],
                confidence=0.85,
            )

        except FileNotFoundError:
            logger.warning(
                f"Tier2: command '{self._tier2_command}' not found — is Claude Code CLI installed?"
            )
            self._breakers["tier2"].record_failure()
            return None
        except Exception as e:
            logger.warning(f"Tier2 (Claude Code CLI) error: {e}")
            self._breakers["tier2"].record_failure()
            return None

    # ─── Tier 3: Cline ────────────────────────────────────────────────────────

    async def _call_tier3(
        self, request: EscalationRequest, task: Task
    ) -> Optional[EscalationResponse]:
        """Attempt to open VS Code with the Cline extension for manual help."""
        import shutil

        # Cline is invoked via 'claude' with special flags or vscode protocol
        if not shutil.which(self._tier3_command):
            logger.warning(
                f"Tier3: command '{self._tier3_command}' not found — Cline unavailable"
            )
            self._breakers["tier3"].record_failure()
            return None

        prompt = self._build_escalation_prompt(request)
        cmd = [self._tier3_command, "--print", prompt]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=self._tier3_timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                logger.warning("Tier3 (Cline) timed out")
                self._breakers["tier3"].record_failure()
                return None

            if proc.returncode != 0:
                self._breakers["tier3"].record_failure()
                return None

            solution = stdout.decode("utf-8", errors="replace")
            return EscalationResponse(
                request_id=request.id,
                tier_used=EscalationTier.TIER3_CLINE,
                tool_used="cline_cli",
                solution=solution[:4096],
                confidence=0.9,
            )
        except Exception as e:
            logger.warning(f"Tier3 (Cline) error: {e}")
            self._breakers["tier3"].record_failure()
            return None

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _build_escalation_prompt(self, request: EscalationRequest) -> str:
        """Build a focused prompt for the escalation tier."""
        errors_str = "\n".join(f"- {e}" for e in request.errors_encountered) or "None"
        steps_str = "\n".join(
            f"- [{s.status.value}] {s.description}" for s in request.steps_attempted
        ) or "No steps attempted"

        return (
            f"Task: {request.task_description}\n\n"
            f"Escalation reason: {request.reason.value}\n\n"
            f"Steps attempted:\n{steps_str}\n\n"
            f"Errors encountered:\n{errors_str}\n\n"
            "Please provide a solution or corrected plan."
        )

    def get_circuit_breaker_states(self) -> dict[str, bool]:
        """Return the open/closed state of each tier's circuit breaker."""
        return {tier: cb.is_open for tier, cb in self._breakers.items()}
