"""Tests for core agent components: ExecutiveAgent, Planner, ToolRouter."""

from __future__ import annotations

import pytest

# ─── ExecutiveAgent ──────────────────────────────────────────────────────────

class TestExecutiveAgent:
    def test_init_defaults(self):
        from src.core.executive import ExecutiveAgent
        from src.core.models import SafetyMode

        agent = ExecutiveAgent()
        assert agent._running is False
        assert agent._paused is False
        assert agent._safety_mode == SafetyMode.FULL
        assert agent._max_concurrent >= 1

    def test_get_status_returns_dict(self):
        from src.core.executive import ExecutiveAgent

        agent = ExecutiveAgent()
        status = agent.get_status()
        assert isinstance(status, dict)
        assert "running" in status
        assert "paused" in status
        assert "safety_mode" in status
        assert "active_tasks" in status
        assert "queued_tasks" in status

    def test_pause_sets_paused(self):
        from src.core.executive import ExecutiveAgent

        agent = ExecutiveAgent()
        agent.pause()
        assert agent._paused is True

    def test_resume_clears_paused(self):
        from src.core.executive import ExecutiveAgent

        agent = ExecutiveAgent()
        agent._paused = True
        agent.resume()
        assert agent._paused is False

    def test_set_safety_mode(self):
        from src.core.executive import ExecutiveAgent
        from src.core.models import SafetyMode

        agent = ExecutiveAgent()
        agent.set_safety_mode(SafetyMode.LIGHT_BYPASS)
        assert agent._safety_mode == SafetyMode.LIGHT_BYPASS

    def test_cannot_set_severe_locked_safety_mode(self):
        from src.core.executive import ExecutiveAgent
        from src.core.models import SafetyMode

        agent = ExecutiveAgent()
        agent._safety_mode = SafetyMode.FULL
        agent.set_safety_mode(SafetyMode.SEVERE_LOCKED)
        # Should remain unchanged
        assert agent._safety_mode == SafetyMode.FULL

    def test_check_ports_no_conflict(self):
        """check_ports passes when ports are free."""
        from src.core.executive import ExecutiveAgent

        agent = ExecutiveAgent()
        # Use high ports unlikely to be in use
        agent._mcp_port = 59901
        agent._ui_port = 59902
        # Should not raise
        agent.check_ports()

    def test_check_ports_conflict_raises_system_exit(self):
        """check_ports exits when port is in use."""
        import socket

        from src.core.executive import ExecutiveAgent

        # Bind a port to simulate conflict
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("localhost", 59903))
            s.listen(1)

            agent = ExecutiveAgent()
            agent._mcp_port = 59903
            agent._ui_port = 59904

            with pytest.raises(SystemExit):
                agent.check_ports()

    async def test_submit_request_returns_task(self):
        from src.core.executive import ExecutiveAgent
        from src.core.models import Task

        agent = ExecutiveAgent()
        agent._running = True
        task = await agent.submit_request("test task")
        assert isinstance(task, Task)
        assert task.request.text == "test task"

    async def test_submit_request_queues_when_at_capacity(self):
        from src.core.executive import ExecutiveAgent
        from src.core.models import Task

        agent = ExecutiveAgent()
        agent._max_concurrent = 1
        agent._running = True

        # Fill up active tasks
        from src.core.models import UserRequest
        mock_task = Task(request=UserRequest(text="existing"))
        agent._active_tasks["fake-id"] = mock_task

        task = await agent.submit_request("queued task")
        assert len(agent._task_queue) == 1

    async def test_save_and_load_checkpoint(self, tmp_path):
        import src.core.executive as exec_mod
        from src.core.executive import ExecutiveAgent

        agent = ExecutiveAgent()

        orig_path = exec_mod.CHECKPOINT_PATH
        exec_mod.CHECKPOINT_PATH = tmp_path / "checkpoint.json"

        try:
            await agent._save_checkpoint()
            assert exec_mod.CHECKPOINT_PATH.exists()

            agent2 = ExecutiveAgent()
            await agent2._load_checkpoint()
            assert agent2._safety_mode == agent._safety_mode
        finally:
            exec_mod.CHECKPOINT_PATH = orig_path


# ─── Planner ──────────────────────────────────────────────────────────────────

class TestPlanner:
    def test_validate_plan_empty_steps(self):
        from src.core.models import Plan
        from src.core.planner import Planner

        planner = Planner()
        plan = Plan(task_id="t1", steps=[], reasoning="none", confidence=0.5)
        valid, msg = planner.validate_plan(plan)
        assert valid is False
        assert "no steps" in msg.lower()

    def test_validate_plan_bad_dependency(self):
        from src.core.models import Plan, PlanStep
        from src.core.planner import Planner

        planner = Planner()
        step = PlanStep(description="step1", depends_on=["nonexistent-id"])
        plan = Plan(task_id="t1", steps=[step], reasoning="test", confidence=0.8)
        valid, msg = planner.validate_plan(plan)
        assert valid is False
        assert "unknown step" in msg.lower()

    def test_validate_plan_valid(self):
        from src.core.models import Plan, PlanStep
        from src.core.planner import Planner

        planner = Planner()
        step = PlanStep(description="step1")
        plan = Plan(task_id="t1", steps=[step], reasoning="test", confidence=0.8)
        valid, msg = planner.validate_plan(plan)
        assert valid is True

    def test_get_ready_steps_no_deps(self):
        from src.core.models import Plan, PlanStep
        from src.core.planner import Planner

        planner = Planner()
        step1 = PlanStep(description="s1")
        step2 = PlanStep(description="s2")
        plan = Plan(task_id="t1", steps=[step1, step2], reasoning="test", confidence=0.8)

        ready = planner.get_ready_steps(plan)
        assert len(ready) == 2

    def test_get_ready_steps_with_deps(self):
        from src.core.models import Plan, PlanStep
        from src.core.planner import Planner

        planner = Planner()
        step1 = PlanStep(description="s1")
        step2 = PlanStep(description="s2", depends_on=[step1.id])
        plan = Plan(task_id="t1", steps=[step1, step2], reasoning="test", confidence=0.8)

        ready = planner.get_ready_steps(plan)
        assert len(ready) == 1
        assert ready[0].id == step1.id

    def test_is_plan_complete_all_succeeded(self):
        from src.core.models import Plan, PlanStep, StepStatus
        from src.core.planner import Planner

        planner = Planner()
        step = PlanStep(description="s1", status=StepStatus.SUCCEEDED)
        plan = Plan(task_id="t1", steps=[step], reasoning="test", confidence=0.8)
        assert planner.is_plan_complete(plan) is True

    def test_is_plan_complete_pending(self):
        from src.core.models import Plan, PlanStep, StepStatus
        from src.core.planner import Planner

        planner = Planner()
        step = PlanStep(description="s1", status=StepStatus.PENDING)
        plan = Plan(task_id="t1", steps=[step], reasoning="test", confidence=0.8)
        assert planner.is_plan_complete(plan) is False

    def test_is_plan_successful_all_succeeded(self):
        from src.core.models import Plan, PlanStep, StepStatus
        from src.core.planner import Planner

        planner = Planner()
        step = PlanStep(description="s1", status=StepStatus.SUCCEEDED)
        plan = Plan(task_id="t1", steps=[step], reasoning="test", confidence=0.8)
        assert planner.is_plan_successful(plan) is True

    def test_is_plan_successful_with_failed(self):
        from src.core.models import Plan, PlanStep, StepStatus
        from src.core.planner import Planner

        planner = Planner()
        step = PlanStep(description="s1", status=StepStatus.FAILED)
        plan = Plan(task_id="t1", steps=[step], reasoning="test", confidence=0.8)
        assert planner.is_plan_successful(plan) is False


# ─── ToolRouter ──────────────────────────────────────────────────────────────

class TestToolRouter:
    async def test_route_to_unknown_tool_returns_error(self):
        from src.core.models import PlanStep
        from src.core.tool_router import ToolRouter
        from src.tools.registry import ToolRegistry

        registry = ToolRegistry()
        router = ToolRouter(registry)
        step = PlanStep(description="test", tool_name="nonexistent_tool")

        result = await router.route(step)
        assert result.success is False
        assert "not registered" in result.error

    async def test_route_to_registered_tool(self):
        from src.core.models import PlanStep
        from src.core.tool_router import ToolRouter
        from src.tools.file_tool import FileTool
        from src.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(FileTool())
        router = ToolRouter(registry)

        step = PlanStep(
            description="list files",
            tool_name="file_tool",
            tool_args={"action": "list", "path": "."},
        )

        result = await router.route(step)
        assert result.tool_name == "file_tool"

    async def test_route_no_tool_name_returns_error(self):
        from src.core.models import PlanStep
        from src.core.tool_router import ToolRouter
        from src.tools.registry import ToolRegistry

        registry = ToolRegistry()
        router = ToolRouter(registry)
        step = PlanStep(description="no tool", tool_name=None)

        result = await router.route(step)
        assert result.success is False
        assert "no tool_name" in result.error
