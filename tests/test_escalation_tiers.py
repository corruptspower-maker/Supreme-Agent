"""Tests for the CEA-style escalation tier modules (tier1, tier2, tier3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models import EscalationReason, EscalationRequest, EscalationTier


@pytest.fixture
def tier1_request() -> EscalationRequest:
    return EscalationRequest(
        task_id="task-1",
        step_id="step-1",
        tier=EscalationTier.TIER1_VSCODE,
        reason=EscalationReason.MAX_RETRIES,
        context="Tool failed after 3 retries",
    )


@pytest.fixture
def tier2_request() -> EscalationRequest:
    return EscalationRequest(
        task_id="task-2",
        step_id="step-2",
        tier=EscalationTier.TIER2_CLAUDE,
        reason=EscalationReason.PARSE_ERROR,
        context="Could not parse agent output",
    )


# ─── Tier 1 Tests ─────────────────────────────────────────────────────────────


class TestTier1Vscode:
    async def test_cline_not_found_raises_runtime_error(self, tier1_request):
        from src.escalation import tier1_vscode

        with patch.object(tier1_vscode, "_run_cline", side_effect=RuntimeError("not found")):
            with pytest.raises(RuntimeError, match="not found"):
                await tier1_vscode.run(tier1_request)

    async def test_successful_run_returns_response(self, tier1_request):
        from src.escalation import tier1_vscode

        mock_output = '{"action":"retry","patch":"sleep(1)","notes":"backoff"}'
        with patch.object(tier1_vscode, "_run_cline", new=AsyncMock(return_value=mock_output)):
            response = await tier1_vscode.run(tier1_request)

        assert response.tier is EscalationTier.TIER1_VSCODE
        assert response.request_id == tier1_request.id
        assert "retry" in response.solution

    async def test_non_json_output_is_wrapped(self, tier1_request):
        from src.escalation import tier1_vscode

        with patch.object(
            tier1_vscode, "_run_cline", new=AsyncMock(return_value="plain text output")
        ):
            response = await tier1_vscode.run(tier1_request)

        assert "plain text output" in response.solution
        assert response.tier is EscalationTier.TIER1_VSCODE

    async def test_confidence_is_high(self, tier1_request):
        from src.escalation import tier1_vscode

        with patch.object(
            tier1_vscode, "_run_cline", new=AsyncMock(return_value='{"action":"retry","patch":"x","notes":"ok"}')
        ):
            response = await tier1_vscode.run(tier1_request)

        assert response.confidence >= 0.8


# ─── Tier 2 Tests ─────────────────────────────────────────────────────────────


class TestTier2Claude:
    async def test_missing_api_key_raises(self, tier2_request):
        from src.escalation import tier2_claude

        with patch.dict("os.environ", {}, clear=True):
            with patch.object(tier2_claude, "_API_KEY", ""):
                with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                    await tier2_claude.run(tier2_request)

    async def test_successful_run_returns_response(self, tier2_request):
        import httpx

        from src.escalation import tier2_claude

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(
            return_value={
                "content": [
                    {"text": '{"action":"retry","patch":"fix","notes":"ok","confidence":0.9}'}
                ],
                "usage": {"output_tokens": 30},
            }
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(tier2_claude, "_API_KEY", "test-key"):
                with patch("src.escalation.tier2_claude.httpx.AsyncClient", return_value=mock_client):
                    response = await tier2_claude.run(tier2_request)

        assert response.tier is EscalationTier.TIER2_CLAUDE
        assert response.request_id == tier2_request.id
        assert "fix" in response.solution

    async def test_confidence_parsed_from_json(self, tier2_request):
        from src.escalation import tier2_claude

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(
            return_value={
                "content": [{"text": '{"action":"skip","patch":"","notes":"","confidence":0.42}'}],
                "usage": {"output_tokens": 10},
            }
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(tier2_claude, "_API_KEY", "test-key"):
                with patch("src.escalation.tier2_claude.httpx.AsyncClient", return_value=mock_client):
                    response = await tier2_claude.run(tier2_request)

        assert abs(response.confidence - 0.42) < 0.01


# ─── EscalationManager initiate() Tests ───────────────────────────────────────


class TestEscalationManagerInitiate:
    @pytest.fixture
    def mgr(self):
        with patch("src.escalation.manager.load_config", side_effect=FileNotFoundError):
            from src.escalation.manager import EscalationManager

            return EscalationManager()

    async def test_initiate_returns_tier1_response(self, mgr):
        from src.core.models import EscalationResponse
        from src.safety.audit_log import AuditLog

        request = EscalationRequest(
            task_id="task-1",
            step_id="step-1",
            tier=EscalationTier.TIER1_VSCODE,
            reason=EscalationReason.MAX_RETRIES,
            context="failed",
        )
        audit = MagicMock(spec=AuditLog)
        audit.log = AsyncMock()

        expected = EscalationResponse(
            request_id=request.id,
            solution='{"action":"retry","patch":"x","notes":"ok"}',
            confidence=0.85,
            tier=EscalationTier.TIER1_VSCODE,
        )

        with patch("src.escalation.tier1_vscode.run", new=AsyncMock(return_value=expected)):
            result = await mgr.initiate(request, audit)

        assert result is not None
        assert result.tier is EscalationTier.TIER1_VSCODE
        audit.log.assert_called_once()

    async def test_initiate_falls_back_to_tier2_when_tier1_fails(self, mgr):
        from src.core.models import EscalationResponse
        from src.safety.audit_log import AuditLog

        request = EscalationRequest(
            task_id="task-2",
            step_id="step-1",
            tier=EscalationTier.TIER1_VSCODE,
            reason=EscalationReason.MAX_RETRIES,
            context="failed",
        )
        audit = MagicMock(spec=AuditLog)
        audit.log = AsyncMock()

        tier2_response = EscalationResponse(
            request_id=request.id,
            solution="tier2 fix",
            confidence=0.9,
            tier=EscalationTier.TIER2_CLAUDE,
        )

        with (
            patch("src.escalation.tier1_vscode.run", side_effect=RuntimeError("cline not found")),
            patch("src.escalation.tier2_claude.run", new=AsyncMock(return_value=tier2_response)),
        ):
            result = await mgr.initiate(request, audit)

        assert result is not None
        assert result.tier is EscalationTier.TIER2_CLAUDE

    async def test_initiate_returns_none_when_all_tiers_fail(self, mgr):
        from src.safety.audit_log import AuditLog

        request = EscalationRequest(
            task_id="task-3",
            step_id="step-1",
            tier=EscalationTier.TIER1_VSCODE,
            reason=EscalationReason.HIGH_RISK,
            context="all failed",
        )
        audit = MagicMock(spec=AuditLog)
        audit.log = AsyncMock()

        with (
            patch("src.escalation.tier1_vscode.run", side_effect=RuntimeError("t1 fail")),
            patch("src.escalation.tier2_claude.run", side_effect=RuntimeError("t2 fail")),
            patch("src.escalation.tier3_browser.run", side_effect=RuntimeError("t3 fail")),
        ):
            result = await mgr.initiate(request, audit)

        assert result is None

    async def test_initiate_skips_lower_tiers(self, mgr):
        """When request.tier is TIER2, tier1 should be skipped."""
        from src.core.models import EscalationResponse
        from src.safety.audit_log import AuditLog

        request = EscalationRequest(
            task_id="task-4",
            step_id="step-1",
            tier=EscalationTier.TIER2_CLAUDE,
            reason=EscalationReason.PARSE_ERROR,
            context="start at tier2",
        )
        audit = MagicMock(spec=AuditLog)
        audit.log = AsyncMock()

        tier2_response = EscalationResponse(
            request_id=request.id,
            solution="tier2 direct",
            confidence=0.9,
            tier=EscalationTier.TIER2_CLAUDE,
        )

        tier1_mock = AsyncMock(return_value=None)
        with (
            patch("src.escalation.tier1_vscode.run", new=tier1_mock),
            patch("src.escalation.tier2_claude.run", new=AsyncMock(return_value=tier2_response)),
        ):
            result = await mgr.initiate(request, audit)

        tier1_mock.assert_not_called()
        assert result is not None
        assert result.tier is EscalationTier.TIER2_CLAUDE
