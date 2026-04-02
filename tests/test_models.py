"""Comprehensive unit tests for all Pydantic models in src.core.models."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.core.models import (
    AuditEntry,
    EscalationReason,
    EscalationRequest,
    EscalationResponse,
    EscalationTier,
    MemoryEntry,
    Plan,
    PlanStep,
    RiskLevel,
    SafetyMode,
    ScreenshotEntry,
    StepStatus,
    Task,
    TaskStatus,
    ToolResult,
    UserRequest,
)


# ---------------------------------------------------------------------------
# Enum smoke tests
# ---------------------------------------------------------------------------


class TestTaskStatus:
    def test_all_values_present(self):
        values = {s.value for s in TaskStatus}
        assert values == {"pending", "planning", "executing", "escalated", "completed", "failed", "cancelled"}

    def test_is_string_enum(self):
        assert TaskStatus.PENDING == "pending"
        assert isinstance(TaskStatus.COMPLETED, str)


class TestRiskLevel:
    def test_all_values(self):
        assert set(RiskLevel) == {RiskLevel.SAFE, RiskLevel.MODERATE, RiskLevel.DANGEROUS, RiskLevel.FORBIDDEN}

    def test_string_coercion(self):
        assert RiskLevel.SAFE == "safe"
        assert RiskLevel.FORBIDDEN == "forbidden"


class TestStepStatus:
    def test_all_values(self):
        expected = {"pending", "running", "succeeded", "failed", "skipped", "escalated"}
        assert {s.value for s in StepStatus} == expected

    def test_default_step_is_pending(self):
        step = PlanStep(description="x")
        assert step.status is StepStatus.PENDING


class TestEscalationTier:
    def test_tier_values(self):
        assert EscalationTier.TIER1_COPILOT == "tier1_copilot"
        assert EscalationTier.TIER2_CLAUDE_CODE == "tier2_claude_code"
        assert EscalationTier.TIER3_CLINE == "tier3_cline"


class TestEscalationReason:
    def test_all_reasons_exist(self):
        reasons = {r.value for r in EscalationReason}
        assert "repeated_failure" in reasons
        assert "missing_mcp_tool" in reasons
        assert len(reasons) == 11


class TestSafetyMode:
    def test_values(self):
        assert SafetyMode.FULL == "full"
        assert SafetyMode.SEVERE_LOCKED == "severe_locked"


# ---------------------------------------------------------------------------
# UserRequest
# ---------------------------------------------------------------------------


class TestUserRequest:
    def test_id_auto_generated(self):
        req = UserRequest(text="hello")
        assert req.id
        assert len(req.id) == 36  # UUID4 length with dashes

    def test_two_instances_have_different_ids(self):
        a = UserRequest(text="hello")
        b = UserRequest(text="hello")
        assert a.id != b.id

    def test_text_required(self):
        with pytest.raises(ValidationError):
            UserRequest()  # type: ignore[call-arg]

    def test_defaults(self):
        req = UserRequest(text="test")
        assert req.source == "cli"
        assert isinstance(req.timestamp, datetime)
        assert req.context == {}

    def test_custom_source(self):
        req = UserRequest(text="test", source="web_ui")
        assert req.source == "web_ui"

    def test_context_dict(self):
        req = UserRequest(text="test", context={"key": "val"})
        assert req.context["key"] == "val"


# ---------------------------------------------------------------------------
# PlanStep
# ---------------------------------------------------------------------------


class TestPlanStep:
    def test_id_auto_generated(self):
        step = PlanStep(description="do something")
        assert step.id

    def test_text_required(self):
        with pytest.raises(ValidationError):
            PlanStep()  # type: ignore[call-arg]

    def test_defaults(self):
        step = PlanStep(description="step")
        assert step.tool_name is None
        assert step.tool_args == {}
        assert step.depends_on == []
        assert step.status is StepStatus.PENDING
        assert step.result is None
        assert step.error is None
        assert step.retry_count == 0
        assert step.max_retries == 3

    def test_retry_fields(self):
        step = PlanStep(description="s", retry_count=2, max_retries=5)
        assert step.retry_count == 2
        assert step.max_retries == 5

    def test_has_retries_left(self):
        step = PlanStep(description="s", retry_count=2, max_retries=3)
        assert step.retry_count < step.max_retries

    def test_no_retries_left(self):
        step = PlanStep(description="s", retry_count=3, max_retries=3)
        assert step.retry_count >= step.max_retries

    def test_tool_args(self):
        step = PlanStep(description="s", tool_name="file_tool", tool_args={"path": "/tmp/x"})
        assert step.tool_args["path"] == "/tmp/x"


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


class TestPlan:
    def test_confidence_valid(self):
        plan = Plan(task_id="t1", steps=[], reasoning="r", confidence=0.75)
        assert plan.confidence == 0.75

    def test_confidence_boundary_zero(self):
        plan = Plan(task_id="t1", steps=[], reasoning="r", confidence=0.0)
        assert plan.confidence == 0.0

    def test_confidence_boundary_one(self):
        plan = Plan(task_id="t1", steps=[], reasoning="r", confidence=1.0)
        assert plan.confidence == 1.0

    def test_confidence_below_zero_raises(self):
        with pytest.raises(ValidationError):
            Plan(task_id="t1", steps=[], reasoning="r", confidence=-0.1)

    def test_confidence_above_one_raises(self):
        with pytest.raises(ValidationError):
            Plan(task_id="t1", steps=[], reasoning="r", confidence=1.1)

    def test_steps_list(self, sample_plan_step):
        plan = Plan(task_id="t1", steps=[sample_plan_step], reasoning="r", confidence=0.5)
        assert len(plan.steps) == 1
        assert plan.steps[0].description == sample_plan_step.description

    def test_id_auto_generated(self):
        plan = Plan(task_id="t1", steps=[], reasoning="r", confidence=0.5)
        assert plan.id

    def test_created_at_is_datetime(self):
        plan = Plan(task_id="t1", steps=[], reasoning="r", confidence=0.5)
        assert isinstance(plan.created_at, datetime)


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------


class TestToolResult:
    def test_success_result(self):
        result = ToolResult(tool_name="file_tool", success=True, output="found it")
        assert result.success is True
        assert result.output == "found it"
        assert result.error is None

    def test_failure_result(self):
        result = ToolResult(tool_name="file_tool", success=False, error="permission denied")
        assert result.success is False
        assert result.error == "permission denied"
        assert result.output is None

    def test_defaults(self):
        result = ToolResult(tool_name="t", success=True)
        assert result.execution_time_ms == 0
        assert result.side_effects == []

    def test_side_effects(self):
        result = ToolResult(tool_name="t", success=True, side_effects=["created /tmp/x"])
        assert "created /tmp/x" in result.side_effects


# ---------------------------------------------------------------------------
# EscalationRequest
# ---------------------------------------------------------------------------


class TestEscalationRequest:
    def test_required_fields(self):
        req = EscalationRequest(
            reason=EscalationReason.REPEATED_FAILURE,
            tier=EscalationTier.TIER1_COPILOT,
            task_description="fix the bug",
            steps_attempted=[],
            errors_encountered=["err1"],
        )
        assert req.reason is EscalationReason.REPEATED_FAILURE
        assert req.tier is EscalationTier.TIER1_COPILOT

    def test_id_auto_generated(self):
        req = EscalationRequest(
            reason=EscalationReason.TIMEOUT,
            tier=EscalationTier.TIER2_CLAUDE_CODE,
            task_description="x",
            steps_attempted=[],
            errors_encountered=[],
        )
        assert req.id

    def test_optional_current_code(self):
        req = EscalationRequest(
            reason=EscalationReason.CODE_GENERATION,
            tier=EscalationTier.TIER1_COPILOT,
            task_description="gen code",
            steps_attempted=[],
            errors_encountered=[],
            current_code="def foo(): pass",
        )
        assert req.current_code == "def foo(): pass"

    def test_context_defaults_empty(self):
        req = EscalationRequest(
            reason=EscalationReason.DEBUGGING,
            tier=EscalationTier.TIER1_COPILOT,
            task_description="debug",
            steps_attempted=[],
            errors_encountered=[],
        )
        assert req.context == {}


# ---------------------------------------------------------------------------
# EscalationResponse
# ---------------------------------------------------------------------------


class TestEscalationResponse:
    def test_basic_response(self):
        resp = EscalationResponse(
            request_id="req-1",
            tier_used=EscalationTier.TIER1_COPILOT,
            tool_used="copilot_api",
            solution="use a try/except block",
            confidence=0.85,
        )
        assert resp.request_id == "req-1"
        assert resp.solution == "use a try/except block"
        assert resp.confidence == 0.85

    def test_confidence_range_lower(self):
        with pytest.raises(ValidationError):
            EscalationResponse(
                request_id="r",
                tier_used=EscalationTier.TIER1_COPILOT,
                tool_used="t",
                solution="s",
                confidence=-0.01,
            )

    def test_confidence_range_upper(self):
        with pytest.raises(ValidationError):
            EscalationResponse(
                request_id="r",
                tier_used=EscalationTier.TIER1_COPILOT,
                tool_used="t",
                solution="s",
                confidence=1.01,
            )

    def test_suggested_steps_default_empty(self):
        resp = EscalationResponse(
            request_id="r",
            tier_used=EscalationTier.TIER2_CLAUDE_CODE,
            tool_used="claude",
            solution="refactor",
            confidence=0.7,
        )
        assert resp.suggested_steps == []
        assert resp.code_changes is None


# ---------------------------------------------------------------------------
# MemoryEntry
# ---------------------------------------------------------------------------


class TestMemoryEntry:
    def test_defaults(self):
        entry = MemoryEntry(category="episodic", content="user said hello")
        assert entry.importance == 0.5
        assert entry.access_count == 0
        assert entry.metadata == {}

    def test_importance_boundary_zero(self):
        entry = MemoryEntry(category="c", content="x", importance=0.0)
        assert entry.importance == 0.0

    def test_importance_boundary_one(self):
        entry = MemoryEntry(category="c", content="x", importance=1.0)
        assert entry.importance == 1.0

    def test_importance_below_zero_raises(self):
        with pytest.raises(ValidationError):
            MemoryEntry(category="c", content="x", importance=-0.1)

    def test_importance_above_one_raises(self):
        with pytest.raises(ValidationError):
            MemoryEntry(category="c", content="x", importance=1.1)

    def test_id_auto_generated(self):
        entry = MemoryEntry(category="c", content="x")
        assert entry.id

    def test_access_count_custom(self):
        entry = MemoryEntry(category="c", content="x", access_count=5)
        assert entry.access_count == 5


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


class TestTask:
    def test_default_status_pending(self, sample_user_request):
        task = Task(request=sample_user_request)
        assert task.status is TaskStatus.PENDING

    def test_id_auto_generated(self, sample_user_request):
        task = Task(request=sample_user_request)
        assert task.id

    def test_two_tasks_different_ids(self, sample_user_request):
        a = Task(request=sample_user_request)
        b = Task(request=sample_user_request)
        assert a.id != b.id

    def test_defaults(self, sample_user_request):
        task = Task(request=sample_user_request)
        assert task.plan is None
        assert task.results == []
        assert task.escalations == []
        assert task.started_at is None
        assert task.completed_at is None
        assert task.error is None

    def test_status_transition_to_executing(self, sample_user_request):
        task = Task(request=sample_user_request)
        task.status = TaskStatus.EXECUTING
        assert task.status is TaskStatus.EXECUTING

    def test_status_transition_to_completed(self, sample_user_request):
        task = Task(request=sample_user_request)
        task.status = TaskStatus.COMPLETED
        assert task.status is TaskStatus.COMPLETED

    def test_attach_plan(self, sample_user_request, sample_plan):
        task = Task(request=sample_user_request)
        task.plan = sample_plan
        assert task.plan is sample_plan

    def test_results_list(self, sample_user_request):
        task = Task(request=sample_user_request)
        task.results.append(ToolResult(tool_name="file_tool", success=True))
        assert len(task.results) == 1


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------


class TestAuditEntry:
    def test_required_fields(self):
        entry = AuditEntry(
            action="file_delete",
            risk_level=RiskLevel.DANGEROUS,
            input_summary="delete /home/user/doc.pdf",
            success=True,
        )
        assert entry.action == "file_delete"
        assert entry.risk_level is RiskLevel.DANGEROUS
        assert entry.success is True

    def test_id_auto_generated(self):
        entry = AuditEntry(
            action="shell_execute",
            risk_level=RiskLevel.DANGEROUS,
            input_summary="ls -la",
            success=False,
        )
        assert entry.id

    def test_optional_fields_default_none(self):
        entry = AuditEntry(
            action="web_search",
            risk_level=RiskLevel.SAFE,
            input_summary="search query",
            success=True,
        )
        assert entry.tool_name is None
        assert entry.user_confirmed is None
        assert entry.output_summary is None
        assert entry.error is None

    def test_timestamp_is_datetime(self):
        entry = AuditEntry(
            action="x",
            risk_level=RiskLevel.SAFE,
            input_summary="y",
            success=True,
        )
        assert isinstance(entry.timestamp, datetime)

    def test_user_confirmed_flag(self):
        entry = AuditEntry(
            action="email_send",
            risk_level=RiskLevel.DANGEROUS,
            input_summary="send email",
            success=True,
            user_confirmed=True,
        )
        assert entry.user_confirmed is True


# ---------------------------------------------------------------------------
# ScreenshotEntry
# ---------------------------------------------------------------------------


class TestScreenshotEntry:
    def test_required_fields(self):
        entry = ScreenshotEntry(image_path="data/screenshots/001.png", description="Browser home page")
        assert entry.image_path == "data/screenshots/001.png"
        assert entry.description == "Browser home page"

    def test_id_auto_generated(self):
        entry = ScreenshotEntry(image_path="x.png", description="d")
        assert entry.id

    def test_timestamp_is_datetime(self):
        entry = ScreenshotEntry(image_path="x.png", description="d")
        assert isinstance(entry.timestamp, datetime)

    def test_action_taken_optional(self):
        entry = ScreenshotEntry(image_path="x.png", description="d")
        assert entry.action_taken is None

    def test_action_taken_set(self):
        entry = ScreenshotEntry(image_path="x.png", description="d", action_taken="click OK button")
        assert entry.action_taken == "click OK button"
