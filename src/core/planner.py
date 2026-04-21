"""Planner: validates and optimizes plans before execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

from src.core.models import Plan, PlanStep, StepFeedback, StepStatus

if TYPE_CHECKING:
    from src.tools.registry import ToolRegistry


class Planner:
    """Validates and manages execution plans."""

    def validate_plan(
        self,
        plan: Plan,
        registry: Optional["ToolRegistry"] = None,
    ) -> tuple[bool, str]:
        """Validate a plan for correctness.

        Checks:
        - Plan has at least one step.
        - All step dependency IDs exist in the plan.
        - Confidence is in [0, 1].
        - (If registry provided) All step tool_names are registered.
        - (If registry provided) Required args are present per tool schema.

        Returns:
            (valid: bool, message: str)
        """
        if not plan.steps:
            return False, "Plan has no steps"

        step_ids = {s.id for s in plan.steps}
        for step in plan.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    return False, f"Step {step.id} depends on unknown step {dep}"

        if plan.confidence < 0.0 or plan.confidence > 1.0:
            return False, f"Invalid confidence: {plan.confidence}"

        if registry is not None:
            for step in plan.steps:
                if not step.tool_name:
                    continue
                if step.tool_name not in registry:
                    return False, f"Unknown tool: '{step.tool_name}' (step: {step.description!r})"
                # Check required args against tool schema
                tool = registry.get(step.tool_name)
                if tool and tool.parameters_schema:
                    required = tool.parameters_schema.get("required", [])
                    missing = [r for r in required if r not in step.tool_args]
                    if missing:
                        return (
                            False,
                            f"Step '{step.description}' tool '{step.tool_name}' missing "
                            f"required args: {missing}",
                        )

        return True, "OK"

    def apply_feedback(
        self,
        plan: Plan,
        feedback: StepFeedback,
        step: PlanStep,
        registry: Optional["ToolRegistry"] = None,
    ) -> None:
        """Mutate *step* in-place according to *feedback*.

        - retry: record current strategy in failed_strategies (no tool change).
        - use_alternative_tool: find a capable alternative tool not in constraints.
        - escalate: mark step as ESCALATED.
        - done / skip: mark step as SKIPPED.
        """
        current_strategy = _describe_strategy(step)

        if feedback.decision == "retry":
            if current_strategy and current_strategy not in step.failed_strategies:
                step.failed_strategies.append(current_strategy)
            logger.debug(f"Planner: retry step '{step.description}'")

        elif feedback.decision == "use_alternative_tool":
            if current_strategy and current_strategy not in step.failed_strategies:
                step.failed_strategies.append(current_strategy)
            alt = self._find_alternative(step, feedback.constraints, registry)
            if alt:
                logger.info(
                    f"Planner: switching step '{step.description}' "
                    f"from '{step.tool_name}' → '{alt}'"
                )
                step.tool_name = alt
                step.tool_args = {}  # caller must repopulate args for new tool
            else:
                logger.warning(
                    f"Planner: no alternative found for step '{step.description}' — escalating"
                )
                step.status = StepStatus.ESCALATED

        elif feedback.decision == "escalate":
            logger.info(f"Planner: escalating step '{step.description}'")
            step.status = StepStatus.ESCALATED

        elif feedback.decision in ("done", "skip"):
            step.status = StepStatus.SKIPPED

    def _find_alternative(
        self,
        step: PlanStep,
        constraints: list[str],
        registry: Optional["ToolRegistry"],
    ) -> Optional[str]:
        """Find a registered tool that can handle the same capability and isn't constrained."""
        if registry is None or not step.tool_name:
            return None
        current_tool = registry.get(step.tool_name)
        if current_tool is None:
            return None
        for capability in (current_tool.capabilities or []):
            alternatives = registry.get_capable_tools(capability)
            for alt in alternatives:
                if alt.name not in constraints and alt.name != step.tool_name:
                    return alt.name
        return None

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


def _describe_strategy(step: PlanStep) -> str:
    """Compact string for the current tool+args strategy."""
    if not step.tool_name:
        return ""
    key_args = {k: v for k, v in step.tool_args.items() if k in ("action", "command", "path", "code")}
    if key_args:
        args_str = ",".join(f"{k}={v}" for k, v in key_args.items())
        return f"{step.tool_name}({args_str})"
    return step.tool_name

