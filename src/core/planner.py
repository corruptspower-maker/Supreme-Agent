"""Planner: validates and optimizes plans before execution."""

from __future__ import annotations

from loguru import logger
from src.core.models import Plan, PlanStep, StepStatus


class Planner:
    """Validates and manages execution plans."""

    def validate_plan(self, plan: Plan) -> tuple[bool, str]:
        """Validate a plan for correctness."""
        if not plan.steps:
            return False, "Plan has no steps"
        
        step_ids = {s.id for s in plan.steps}
        for step in plan.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    return False, f"Step {step.id} depends on unknown step {dep}"
        
        if plan.confidence < 0.0 or plan.confidence > 1.0:
            return False, f"Invalid confidence: {plan.confidence}"
        
        return True, "OK"

    def get_ready_steps(self, plan: Plan) -> list[PlanStep]:
        """Return steps whose dependencies are all satisfied."""
        completed = {s.id for s in plan.steps if s.status == StepStatus.SUCCEEDED}
        failed = {s.id for s in plan.steps if s.status == StepStatus.FAILED}
        
        ready = []
        for step in plan.steps:
            if step.status != StepStatus.PENDING:
                continue
            if all(dep in completed for dep in step.depends_on):
                if not any(dep in failed for dep in step.depends_on):
                    ready.append(step)
        return ready

    def is_plan_complete(self, plan: Plan) -> bool:
        """Check if all steps are in a terminal state."""
        terminal = {StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.SKIPPED, StepStatus.ESCALATED}
        return all(s.status in terminal for s in plan.steps)

    def is_plan_successful(self, plan: Plan) -> bool:
        """Check if all non-skipped steps succeeded."""
        for s in plan.steps:
            if s.status not in {StepStatus.SUCCEEDED, StepStatus.SKIPPED}:
                return False
        return True
