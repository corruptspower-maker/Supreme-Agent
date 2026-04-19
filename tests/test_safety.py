"""Tests for the safety manager."""

from __future__ import annotations

from unittest.mock import patch

import pytest

# ─── SafetyManager ────────────────────────────────────────────────────────────


@pytest.fixture
async def safety(tmp_path):
    with patch("src.safety.manager.load_config") as mock_cfg:
        mock_cfg.return_value = {
            "safety": {
                "require_confirmation": ["email_send", "file_delete"],
                "forbidden_actions": ["registry_edit", "system_file_modification"],
                "rate_limits": {
                    "email_send": {"max": 2, "period_hours": 1},
                },
                "audit_db_path": str(tmp_path / "audit.db"),
            }
        }
        from src.safety.manager import SafetyManager

        m = SafetyManager()
        await m.start()
        return m


class TestSafetyManagerPlanApproval:
    async def test_approves_safe_plan(self, safety):
        from src.core.models import Plan, PlanStep, SafetyMode

        step = PlanStep(description="Search web", tool_name="web_search_tool")
        plan = Plan(task_id="t1", steps=[step], reasoning="ok", confidence=0.9)

        approved, reason = await safety.check_plan(plan, SafetyMode.FULL)
        assert approved is True

    async def test_blocks_forbidden_tool(self, safety):
        from src.core.models import Plan, PlanStep, SafetyMode

        step = PlanStep(description="Edit registry", tool_name="registry_edit")
        plan = Plan(task_id="t1", steps=[step], reasoning="bad", confidence=0.9)

        approved, reason = await safety.check_plan(plan, SafetyMode.FULL)
        assert approved is False
        assert "forbidden" in reason.lower()

    async def test_blocks_unconfirmed_dangerous_tool(self, safety):
        from src.core.models import Plan, PlanStep, SafetyMode

        step = PlanStep(description="Send email", tool_name="email_send")
        plan = Plan(task_id="t1", steps=[step], reasoning="email", confidence=0.9)

        approved, reason = await safety.check_plan(plan, SafetyMode.FULL)
        assert approved is False
        assert "confirmation" in reason.lower()

    async def test_allows_confirmed_dangerous_tool(self, safety):
        from src.core.models import Plan, PlanStep, SafetyMode

        step = PlanStep(
            description="Send email",
            tool_name="email_send",
            tool_args={"confirmed": True},
        )
        plan = Plan(task_id="t1", steps=[step], reasoning="email", confidence=0.9)

        approved, _ = await safety.check_plan(plan, SafetyMode.FULL)
        assert approved is True

    async def test_severe_locked_blocks_all(self, safety):
        from src.core.models import Plan, PlanStep, SafetyMode

        step = PlanStep(description="Safe step", tool_name="web_search_tool")
        plan = Plan(task_id="t1", steps=[step], reasoning="ok", confidence=0.9)

        approved, reason = await safety.check_plan(plan, SafetyMode.SEVERE_LOCKED)
        assert approved is False
        assert "SEVERE_LOCKED" in reason

    async def test_light_bypass_skips_confirmation(self, safety):
        """In LIGHT_BYPASS mode, dangerous tools don't require confirmed=True."""
        from src.core.models import Plan, PlanStep, SafetyMode

        step = PlanStep(description="Delete file", tool_name="file_delete")
        plan = Plan(task_id="t1", steps=[step], reasoning="cleanup", confidence=0.9)

        approved, _ = await safety.check_plan(plan, SafetyMode.LIGHT_BYPASS)
        assert approved is True


class TestSafetyManagerRateLimits:
    async def test_rate_limit_enforced(self, safety):
        from src.core.models import Plan, PlanStep, SafetyMode

        # max 2 email_send per hour
        for _ in range(2):
            step = PlanStep(
                description="Send email", tool_name="email_send", tool_args={"confirmed": True}
            )
            plan = Plan(task_id="t", steps=[step], reasoning="ok", confidence=0.9)
            await safety.check_plan(plan, SafetyMode.FULL)

        step = PlanStep(
            description="Send email again",
            tool_name="email_send",
            tool_args={"confirmed": True},
        )
        plan = Plan(task_id="t", steps=[step], reasoning="ok", confidence=0.9)
        approved, reason = await safety.check_plan(plan, SafetyMode.FULL)
        assert approved is False
        assert "rate limit" in reason.lower() or "max" in reason.lower()


class TestSafetyManagerAudit:
    async def test_log_and_retrieve_audit(self, safety):
        from src.core.models import AuditEntry, RiskLevel

        entry = AuditEntry(
            action="file_read",
            tool_name="file_tool",
            risk_level=RiskLevel.SAFE,
            input_summary="read /tmp/test.txt",
            output_summary="file contents",
            success=True,
        )
        await safety.log_audit(entry)

        entries = await safety.get_recent_audit(limit=10)
        assert len(entries) >= 1
        assert any(e["action"] == "file_read" for e in entries)

    async def test_audit_records_failure(self, safety):
        from src.core.models import AuditEntry, RiskLevel

        entry = AuditEntry(
            action="shell_execute",
            tool_name="shell_tool",
            risk_level=RiskLevel.DANGEROUS,
            input_summary="rm -rf /",
            success=False,
            error="Forbidden command",
        )
        await safety.log_audit(entry)

        entries = await safety.get_recent_audit(limit=10)
        failed = [e for e in entries if e["action"] == "shell_execute"]
        assert len(failed) >= 1
        assert failed[0]["success"] == 0  # SQLite stores bool as int
