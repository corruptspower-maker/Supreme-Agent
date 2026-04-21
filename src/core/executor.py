"""Task executor — runs plans step by step with the post-execution pipeline."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from loguru import logger

from src.core.models import (
    EscalationReason,
    PlanStep,
    Plan,
    StepStatus,
    Task,
    TaskStatus,
    ToolResult,
)
from src.core.post_execution import (
    FeedbackEngine,
    OutcomeInterpreter,
    ResultNormalizer,
    VerificationLayer,
)
from src.core.tool_router import ToolRouter
from src.utils.screenshot import capture_screenshot_async


class Executor:
    """Executes plans step by step with a closed-loop feedback pipeline."""

    def __init__(
        self,
        router: ToolRouter,
        escalation_manager=None,
        safety_manager=None,
    ) -> None:
        self._router = router
        self._escalation = escalation_manager
        self._safety = safety_manager

        # Post-execution pipeline (reverse abstraction layer)
        self._normalizer = ResultNormalizer()
        self._verifier = VerificationLayer()
        self._interpreter = OutcomeInterpreter()
        self._feedback_engine = FeedbackEngine()

    async def execute_plan(self, task: Task, registry=None) -> Task:
        """Execute a plan, updating task state with feedback at each step.

        Args:
            task: The task with an attached Plan.
            registry: Optional ToolRegistry for plan validation.
        """
        if task.plan is None:
            task.status = TaskStatus.FAILED
            task.error = "No plan to execute"
            return task

        task.status = TaskStatus.EXECUTING
        plan = task.plan

        from src.core.planner import Planner
        planner = Planner()

        # P0: Validate plan before any execution
        valid, reason = planner.validate_plan(plan, registry=registry)
        if not valid:
            task.status = TaskStatus.FAILED
            task.error = f"Plan validation failed: {reason}"
            logger.error(f"Plan validation failed for task {task.id}: {reason}")
            return task

        while not planner.is_plan_complete(plan):
            ready = planner.get_ready_steps(plan)
            if not ready:
                break

            for step in ready:
                await self._execute_step(task, step, plan, planner)

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
            escalated_steps = [s for s in plan.steps if s.status == StepStatus.ESCALATED]
            if self._escalation and (failed_steps or escalated_steps):
                await self._handle_escalation(task, failed_steps + escalated_steps)
            else:
                task.status = TaskStatus.FAILED
                task.error = f"{len(failed_steps)} steps failed"

        task.completed_at = datetime.utcnow()
        return task

    async def _execute_step(
        self,
        task: Task,
        step: PlanStep,
        plan: Plan,
        planner,
    ) -> None:
        """Execute *step* with the full post-execution feedback loop."""
        step.status = StepStatus.RUNNING
        goal = step.description  # goal context for interpreter

        # Safety pre-check (per-step)
        if self._safety and step.tool_name:
            from src.core.models import Plan as PlanModel
            mini_plan = PlanModel(
                task_id=task.id,
                steps=[step],
                reasoning="single-step safety check",
                confidence=1.0,
            )
            from src.core.models import SafetyMode
            approved, reason = await self._safety.check_plan(mini_plan, SafetyMode.FULL)
            if not approved:
                feedback = self._safety.annotate_blocked(step)
                planner.apply_feedback(plan, feedback, step)
                task.last_feedback = feedback
                logger.warning(f"Safety blocked step '{step.description}': {reason}")
                return

        while step.retry_count <= step.max_retries:
            # Execute (dumb — raw output only)
            raw_result = await self._router.route(step)
            task.results.append(raw_result)

            # Normalize
            normalized = self._normalizer.normalize(raw_result)
            task.last_normalized = normalized

            # Verify
            verified = self._verifier.verify(step, raw_result)

            if verified.verified:
                step.status = StepStatus.SUCCEEDED
                step.result = raw_result.output
                logger.info(f"Step verified ✓: {step.description}")
                return

            # Interpret
            interpreted = self._interpreter.interpret(normalized, goal)

            # Feedback
            feedback = self._feedback_engine.build(step, normalized, interpreted, verified)
            task.last_feedback = feedback

            logger.warning(
                f"Step '{step.description}' unverified "
                f"(attempt {step.retry_count + 1}/{step.max_retries + 1}): "
                f"{interpreted.reason} — decision={feedback.decision}"
            )

            if feedback.decision in ("escalate",):
                step.status = StepStatus.ESCALATED
                return

            if feedback.decision == "use_alternative_tool":
                planner.apply_feedback(plan, feedback, step)
                if step.status == StepStatus.ESCALATED:
                    return
                # Reset retry count for the new tool
                step.retry_count = 0
                continue

            # retry
            planner.apply_feedback(plan, feedback, step)
            step.retry_count += 1
            if step.retry_count > step.max_retries:
                break
            await asyncio.sleep(1.0)

        step.status = StepStatus.FAILED
        step.error = raw_result.error or verified.mismatch

    async def _handle_escalation(self, task: Task, failed_steps: list[PlanStep]) -> None:
        """Escalate failed/escalated steps to a higher-capability system."""
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
                tier = response.tier_used or response.tier
                logger.info(f"Escalation succeeded via {tier}")
            else:
                task.status = TaskStatus.FAILED
                task.error = "All escalation tiers exhausted"
        except Exception as e:
            logger.error(f"Escalation error: {e}")
            task.status = TaskStatus.FAILED
            task.error = f"Escalation failed: {e}"

