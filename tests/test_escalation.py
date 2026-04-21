"""Tests for the escalation manager and circuit breaker."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── CircuitBreaker ───────────────────────────────────────────────────────────


class TestCircuitBreaker:
    def _make(self, threshold=2, recovery=10):
        from src.escalation.manager import _CircuitBreaker

        return _CircuitBreaker(failure_threshold=threshold, recovery_timeout=recovery)

    def test_initially_closed(self):
        cb = self._make()
        assert cb.is_open is False

    def test_opens_after_threshold(self):
        cb = self._make(threshold=2)
        cb.record_failure()
        assert cb.is_open is False
        cb.record_failure()
        assert cb.is_open is True

    def test_success_resets_failures(self):
        cb = self._make(threshold=2)
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        assert cb.is_open is False

    def test_half_open_after_recovery(self):

        cb = self._make(threshold=2, recovery=0)
        cb.record_failure()
        cb.record_failure()
        # Circuit is opened; with recovery=0 the next is_open check already transitions
        # to half-open (returns False) so further calls are allowed
        assert cb.is_open is False  # recovery_timeout=0 → half-open immediately


# ─── EscalationManager ────────────────────────────────────────────────────────


@pytest.fixture
def escalation_cfg():
    return {
        "escalation": {
            "triggers": {
                "max_retries_before_escalate": 3,
                "min_confidence_threshold": 0.4,
            },
            "routing": {"code_generation": "tier1", "debugging": "tier1"},
            "fallback_chain": ["tier1", "tier2", "tier3"],
            "circuit_breaker": {"failure_threshold": 3, "recovery_timeout_seconds": 300},
        }
    }


@pytest.fixture
def models_cfg():
    return {
        "escalation": {
            "tier1": {
                "base_url": "https://api.githubcopilot.com",
                "model": "gpt-4o",
                "timeout_seconds": 30,
            },
            "tier2": {
                "command": "claude",
                "flags": ["--print"],
                "timeout_seconds": 300,
            },
            "tier3": {"command": "claude", "timeout_seconds": 600},
        }
    }


@pytest.fixture
def mgr(escalation_cfg):
    def _load(name):
        if name == "escalation":
            return escalation_cfg
        return {}

    with patch("src.escalation.manager.load_config", side_effect=_load):
        from src.escalation.manager import EscalationManager

        return EscalationManager()


class TestEscalationManagerCircuitBreaker:
    def test_initial_circuit_breakers_closed(self, mgr):
        states = mgr.get_circuit_breaker_states()
        assert all(not v for v in states.values())

    def test_circuit_breaker_opens_after_failures(self, mgr):
        for _ in range(3):
            mgr._breakers["tier1"].record_failure()
        assert mgr._breakers["tier1"].is_open is True

    async def test_open_circuit_is_skipped(self, mgr):
        from src.core.models import EscalationReason, Task, UserRequest

        mgr._breakers["tier1"].record_failure()
        mgr._breakers["tier1"].record_failure()
        mgr._breakers["tier1"].record_failure()
        # tier2 and tier3 also open
        mgr._breakers["tier2"].record_failure()
        mgr._breakers["tier2"].record_failure()
        mgr._breakers["tier2"].record_failure()
        mgr._breakers["tier3"].record_failure()
        mgr._breakers["tier3"].record_failure()
        mgr._breakers["tier3"].record_failure()

        req = UserRequest(text="complex task")
        task = Task(request=req)
        result = await mgr.escalate(task, EscalationReason.REPEATED_FAILURE)
        assert result is None  # All open → None returned


class TestEscalationManagerTier1:
    async def test_tier1_cline_not_found_returns_none(self, mgr):
        from unittest.mock import AsyncMock, patch

        from src.core.models import (
            EscalationReason,
            EscalationRequest,
            EscalationTier,
            Task,
            UserRequest,
        )

        req = UserRequest(text="generate code")
        task = Task(request=req)

        esc_req = EscalationRequest(
            reason=EscalationReason.REPEATED_FAILURE,
            tier=EscalationTier.TIER1_VSCODE,
            task_description="test",
            steps_attempted=[],
            errors_encountered=[],
        )

        with patch(
            "src.escalation.tier1_vscode.run",
            side_effect=RuntimeError("Cline executable 'cline' not found"),
        ):
            resp = await mgr._call_tier1(esc_req, task)
        assert resp is None


class TestEscalationManagerTier2:
    async def test_tier2_no_api_key_returns_none(self, mgr):
        from unittest.mock import AsyncMock, patch

        from src.core.models import (
            EscalationReason,
            EscalationRequest,
            EscalationTier,
            Task,
            UserRequest,
        )

        req = UserRequest(text="debug code")
        task = Task(request=req)
        esc_req = EscalationRequest(
            reason=EscalationReason.DEBUGGING,
            tier=EscalationTier.TIER2_CLAUDE,
            task_description="debug this",
            steps_attempted=[],
            errors_encountered=["NameError: name 'x' is not defined"],
        )

        with patch(
            "src.escalation.tier2_claude.run",
            side_effect=RuntimeError("ANTHROPIC_API_KEY is not set"),
        ):
            result = await mgr._call_tier2(esc_req, task)
        assert result is None

    async def test_tier2_returns_solution(self, mgr):
        from unittest.mock import AsyncMock, patch

        from src.core.models import (
            EscalationReason,
            EscalationRequest,
            EscalationResponse,
            EscalationTier,
            Task,
            UserRequest,
        )

        req = UserRequest(text="debug code")
        task = Task(request=req)
        esc_req = EscalationRequest(
            reason=EscalationReason.DEBUGGING,
            tier=EscalationTier.TIER2_CLAUDE,
            task_description="debug this",
            steps_attempted=[],
            errors_encountered=[],
        )

        mock_response = EscalationResponse(
            request_id=esc_req.id,
            solution='{"action":"retry","patch":"Use a try-except block","notes":"ok"}',
            confidence=0.85,
            tier=EscalationTier.TIER2_CLAUDE,
        )

        with patch("src.escalation.tier2_claude.run", new=AsyncMock(return_value=mock_response)):
            result = await mgr._call_tier2(esc_req, task)

        assert result is not None
        assert "try-except" in result.solution


class TestEscalationManagerPromptBuilding:
    def test_prompt_includes_task_and_errors(self, mgr):
        from src.core.models import EscalationReason, EscalationRequest, EscalationTier

        req = EscalationRequest(
            reason=EscalationReason.REPEATED_FAILURE,
            tier=EscalationTier.TIER1_COPILOT,
            task_description="Write a web scraper",
            steps_attempted=[],
            errors_encountered=["ConnectionError: timed out", "SSL error"],
        )
        prompt = mgr._build_escalation_prompt(req)
        assert "web scraper" in prompt
        assert "ConnectionError" in prompt
        assert "SSL error" in prompt
        assert "repeated_failure" in prompt
