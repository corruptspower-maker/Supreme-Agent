"""Escalation manager — multi-tier escalation with circuit breaker."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from loguru import logger

from src.core.models import (
    EscalationLogEntry,
    EscalationReason,
    EscalationRequest,
    EscalationResponse,
    EscalationTier,
    Task,
)
from src.utils import metrics
from src.utils.config import load_config
from src.utils.logging import json_log

if TYPE_CHECKING:
    from src.safety.audit_log import AuditLog

# Ordered tier mapping for initiate() fallback chain
_TIER_ORDER: dict[EscalationTier, int] = {
    EscalationTier.TIER1_VSCODE: 1,
    EscalationTier.TIER2_CLAUDE: 2,
    EscalationTier.TIER3_BROWSER: 3,
}


class _CircuitBreaker:
    """Simple per-tier circuit breaker (private, backward-compatible SA API).

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


class CircuitBreaker:
    """Public multi-tier circuit breaker (CEA API).

    States: CLOSED (normal) → OPEN (failing) → HALF-OPEN (testing).

    Args:
        threshold: Number of consecutive failures to open the circuit.
        reset_seconds: Seconds to wait before moving from OPEN to HALF-OPEN.
    """

    def __init__(self, threshold: int = 5, reset_seconds: float = 60.0) -> None:
        self._threshold = threshold
        self._reset_seconds = reset_seconds
        self._failures: dict[EscalationTier, int] = {}
        self._opened_at: dict[EscalationTier, float] = {}

    def is_open(self, tier: EscalationTier) -> bool:
        """Return True if the circuit for *tier* is OPEN."""
        failures = self._failures.get(tier, 0)
        if failures < self._threshold:
            return False
        opened = self._opened_at.get(tier, 0.0)
        if time.monotonic() - opened >= self._reset_seconds:
            self._failures[tier] = 0
            return False
        return True

    def record_success(self, tier: EscalationTier) -> None:
        """Record a successful call, resetting the failure counter for *tier*."""
        self._failures[tier] = 0
        self._opened_at.pop(tier, None)

    def record_failure(self, tier: EscalationTier) -> None:
        """Record a failed call for *tier*."""
        self._failures[tier] = self._failures.get(tier, 0) + 1
        if self._failures[tier] >= self._threshold:
            self._opened_at[tier] = time.monotonic()


class EscalationManager:
    """Orchestrates escalation through up to three tiers.

    Tier 1 — Cline CLI via VS Code subprocess
    Tier 2 — Anthropic Claude API (httpx)
    Tier 3 — Playwright browser automation

    Each tier has an independent circuit breaker. The fallback chain is
    configurable via escalation.yaml.

    Supports two calling styles:

    - ``escalate(task, reason, errors)`` — original SA style
    - ``initiate(request, audit)`` — CEA style with per-tier fallback
    """

    def __init__(self) -> None:
        try:
            esc_cfg = load_config("escalation").get("escalation", {})
        except (FileNotFoundError, ValueError):
            esc_cfg = {}

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
        self._cb = CircuitBreaker(threshold=cb_threshold, reset_seconds=cb_recovery)

    # ─── CEA-style API ────────────────────────────────────────────────────────

    async def initiate(
        self,
        request: EscalationRequest,
        audit: "AuditLog",
    ) -> Optional[EscalationResponse]:
        """Attempt escalation starting at request.tier, falling back through higher tiers.

        CEA-compatible entry point. Uses the shared CircuitBreaker (self._cb).

        Args:
            request: The EscalationRequest with failure context.
            audit: AuditLog instance to record escalation events.

        Returns:
            First successful EscalationResponse, or None if all tiers exhausted.
        """
        await metrics.inc("escalations_total")
        start_order = _TIER_ORDER.get(request.tier, 1)

        for tier, order in sorted(_TIER_ORDER.items(), key=lambda x: x[1]):
            if order < start_order:
                continue
            if self._cb.is_open(tier):
                json_log("circuit_open", tier=tier.name)
                continue
            try:
                response = await self._invoke_tier(tier, request)
                if response is not None:
                    self._cb.record_success(tier)
                    await audit.log(
                        EscalationLogEntry(
                            task_id=request.task_id,
                            step_id=request.step_id,
                            event="escalation_resolved",
                            details=f"tier={tier.name} solution={response.solution[:100]}",
                        )
                    )
                    json_log(
                        "escalation_resolved",
                        tier=tier.name,
                        task_id=request.task_id,
                    )
                    return response
            except Exception as exc:
                self._cb.record_failure(tier)
                json_log("escalation_tier_failed", tier=tier.name, error=str(exc))

        return None

    async def _invoke_tier(
        self, tier: EscalationTier, request: EscalationRequest
    ) -> Optional[EscalationResponse]:
        """Delegate to the correct tier module (used by initiate())."""
        if tier == EscalationTier.TIER1_VSCODE:
            from src.escalation import tier1_vscode

            return await tier1_vscode.run(request)
        elif tier == EscalationTier.TIER2_CLAUDE:
            from src.escalation import tier2_claude

            return await tier2_claude.run(request)
        else:
            from src.escalation import tier3_browser

            return await tier3_browser.run(request)

    # ─── SA-style API ─────────────────────────────────────────────────────────

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
            tier=EscalationTier.TIER1_VSCODE,
            task_description=task.request.text,
            steps_attempted=task.plan.steps if task.plan else [],
            errors_encountered=errors or [],
            task_id=task.id,
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

    # ─── Tier implementations (delegate to tier modules) ─────────────────────

    async def _call_tier1(
        self, request: EscalationRequest, task: Task
    ) -> Optional[EscalationResponse]:
        """Invoke Tier-1 (Cline CLI) escalation."""
        self._prepare_request(request, task)
        try:
            from src.escalation import tier1_vscode

            response = await tier1_vscode.run(request)
            self._breakers["tier1"].record_success()
            return response
        except Exception as e:
            logger.warning(f"Tier1 (Cline CLI) failed: {e}")
            self._breakers["tier1"].record_failure()
            return None

    async def _call_tier2(
        self, request: EscalationRequest, task: Task
    ) -> Optional[EscalationResponse]:
        """Invoke Tier-2 (Anthropic Claude API) escalation."""
        self._prepare_request(request, task)
        try:
            from src.escalation import tier2_claude

            response = await tier2_claude.run(request)
            self._breakers["tier2"].record_success()
            return response
        except Exception as e:
            logger.warning(f"Tier2 (Anthropic API) failed: {e}")
            self._breakers["tier2"].record_failure()
            return None

    async def _call_tier3(
        self, request: EscalationRequest, task: Task
    ) -> Optional[EscalationResponse]:
        """Invoke Tier-3 (Playwright browser) escalation."""
        self._prepare_request(request, task)
        try:
            from src.escalation import tier3_browser

            response = await tier3_browser.run(request)
            self._breakers["tier3"].record_success()
            return response
        except Exception as e:
            logger.warning(f"Tier3 (Playwright browser) failed: {e}")
            self._breakers["tier3"].record_failure()
            return None

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _prepare_request(
        self, request: EscalationRequest, task: Optional[Task] = None
    ) -> None:
        """Populate tier-module-required fields if not already set."""
        if not request.context:
            request.context = self._build_escalation_prompt(request)
        if not request.task_id and task is not None:
            request.task_id = task.id

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
