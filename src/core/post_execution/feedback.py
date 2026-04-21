"""FeedbackEngine — builds a StepFeedback decision from pipeline results.

Decision logic (in priority order):
  1. verified=True          → (should not reach here) succeed
  2. PERMISSION error       → escalate
  3. strategy already tried → use_alternative_tool
  4. max retries reached    → escalate
  5. else                   → retry
"""

from __future__ import annotations

from src.core.models import (
    ErrorType,
    InterpretedOutcome,
    NormalizedResult,
    PlanStep,
    StepFeedback,
    VerificationResult,
)


class FeedbackEngine:
    """Produces a StepFeedback decision to feed back to the planner."""

    def build(
        self,
        step: PlanStep,
        normalized: NormalizedResult,
        interpreted: InterpretedOutcome,
        verified: VerificationResult,
    ) -> StepFeedback:
        """Decide what the planner should do next for *step*.

        Args:
            step: The plan step that was executed.
            normalized: Classified result from ResultNormalizer.
            interpreted: Semantic outcome from OutcomeInterpreter.
            verified: Reality check from VerificationLayer.

        Returns:
            StepFeedback with decision and constraints.
        """
        if verified.verified:
            return StepFeedback(decision="done", strategy="verified success")

        error_type = normalized.error_type
        current_strategy = _describe_strategy(step)

        # 1. Permission errors must escalate — retrying won't help
        if error_type == ErrorType.PERMISSION:
            return StepFeedback(
                decision="escalate",
                strategy=current_strategy,
                constraints=[step.tool_name or ""],
            )

        # 2. Already tried this exact strategy — use an alternative
        if current_strategy and current_strategy in step.failed_strategies:
            return StepFeedback(
                decision="use_alternative_tool",
                strategy=current_strategy,
                constraints=list(step.failed_strategies) + [step.tool_name or ""],
            )

        # 3. Max retries reached — escalate
        if step.retry_count >= step.max_retries:
            return StepFeedback(
                decision="escalate",
                strategy=current_strategy,
                constraints=[step.tool_name or ""],
            )

        # 4. NOT_FOUND with a hint → retry with the hint as guidance
        if error_type == ErrorType.NOT_FOUND and interpreted.next_strategy_hint:
            return StepFeedback(
                decision="retry",
                strategy=interpreted.next_strategy_hint,
                constraints=[],
            )

        # 5. Default: retry
        return StepFeedback(
            decision="retry",
            strategy=current_strategy or "retry previous strategy",
            constraints=[],
        )


def _describe_strategy(step: PlanStep) -> str:
    """Produce a compact string describing the current tool+args strategy."""
    if not step.tool_name:
        return ""
    # Include key args to differentiate strategies on the same tool
    key_args = {k: v for k, v in step.tool_args.items() if k in ("action", "command", "path", "code")}
    if key_args:
        args_str = ",".join(f"{k}={v}" for k, v in key_args.items())
        return f"{step.tool_name}({args_str})"
    return step.tool_name
