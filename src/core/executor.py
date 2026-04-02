"""Task executor — runs plans step by step with retry and escalation."""

from __future__ import annotations

import asyncio
from datetime import datetime

from loguru import logger

from src.core.models import (
    EscalationReason,
    PlanStep,
    StepStatus,
    Task,
    TaskStatus,
)
from src.core.tool_router import ToolRouter
from src.utils.screenshot import capture_screenshot_async


class Executor:
    """Executes plans step by step."""

    def __init__(
        self,
        router: ToolRouter,
        escalation_manager=None,
        safety_manager=None,
    ) -> None:
        self._router = router
        self._escalation = escalation_manager
        self._safety = safety_manager

    async def execute_plan(self, task: Task) -> Task:
        """Execute a plan, updating task state throughout."""
        if task.plan is None:
            task.status = TaskStatus.FAILED
            task.error = "No plan to execute"
            return task

        task.status = TaskStatus.EXECUTING
        plan = task.plan

        from src.core.planner import Planner
        planner = Planner()

        while not planner.is_plan_complete(plan):
            ready = planner.get_ready_steps(plan)
            if not ready:
                break

            for step in ready:
                await self._execute_step(task, step)

                asyncio.create_task(
                    capture_screenshot_async(
                        description=f"After step: {step.description}",
                        action_taken=step.tool_name or "none",
                    )
                )

        if planner.is_plan_successful(plan):
            task.status = TaskStatus.COMPLETED
        else:
            failed_steps = [s for s in plan.steps if s.status == StepStatus.FAILED]
            if self._escalation and failed_steps:
                await self._handle_escalation(task, failed_steps)
            else:
                task.status = TaskStatus.FAILED
                task.error = f"{len(failed_steps)} steps failed"

        task.completed_at = datetime.utcnow()
        return task

    async def _execute_step(self, task: Task, step: PlanStep) -> None:
        """Execute a single step with retry logic."""
        step.status = StepStatus.RUNNING

        while step.retry_count <= step.max_retries:
            result = await self._router.route(step)
            task.results.append(result)

            if result.success:
                step.status = StepStatus.SUCCEEDED
                step.result = result.output
                logger.info(f"Step succeeded: {step.description}")
                return

            step.retry_count += 1
            step.error = result.error
            logger.warning(
                f"Step failed (attempt {step.retry_count}/{step.max_retries}): "
                f"{step.description} — {result.error}"
            )

            if step.retry_count > step.max_retries:
                break

            await asyncio.sleep(1.0)

        step.status = StepStatus.FAILED

    async def _handle_escalation(self, task: Task, failed_steps: list[PlanStep]) -> None:
        """Escalate failed steps to a higher-capability system."""
        if self._escalation is None:
            task.status = TaskStatus.FAILED
            task.error = "Steps failed and no escalation manager available"
            return

        task.status = TaskStatus.ESCALATED
        errors = [s.error or "unknown" for s in failed_steps]

        try:
            response = await self._escalation.escalate(
                task=task,
                reason=EscalationReason.REPEATED_FAILURE,
                errors=errors,
            )
            if response:
                task.status = TaskStatus.COMPLETED
                logger.info(f"Escalation succeeded via {response.tier_used}")
            else:
                task.status = TaskStatus.FAILED
                task.error = "All escalation tiers exhausted"
        except Exception as e:
            logger.error(f"Escalation error: {e}")
            task.status = TaskStatus.FAILED
            task.error = f"Escalation failed: {e}"
