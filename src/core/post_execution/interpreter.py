"""OutcomeInterpreter — translates NormalizedResult into goal-relative meaning."""

from __future__ import annotations

from src.core.models import ErrorType, InterpretedOutcome, NormalizedResult

# ─── Strategy hint lookup: (error_type, goal_keyword) → hint ─────────────────

_HINTS: dict[tuple[ErrorType, str], str] = {
    (ErrorType.NOT_FOUND, "write"): "create parent directories before writing",
    (ErrorType.NOT_FOUND, "read"): "verify the file path is correct before reading",
    (ErrorType.NOT_FOUND, "import"): "install the missing package with pip/uv",
    (ErrorType.NOT_FOUND, "run"): "check the executable is installed and on PATH",
    (ErrorType.NOT_FOUND, "delete"): "file already absent — step may be a no-op",
    (ErrorType.SYNTAX, "python"): "fix the syntax error before re-running",
    (ErrorType.SYNTAX, "json"): "validate JSON structure before parsing",
    (ErrorType.SYNTAX, "shell"): "review shell command quoting and escaping",
    (ErrorType.PERMISSION, ""): "run with elevated privileges or change file ownership",
    (ErrorType.TIMEOUT, "api"): "increase timeout or retry with backoff",
    (ErrorType.TIMEOUT, "http"): "increase timeout or retry with backoff",
    (ErrorType.TIMEOUT, "test"): "profile test for infinite loops or blocking calls",
    (ErrorType.TOOL_FAILURE, ""): "try an alternative tool or verify tool configuration",
}


def _goal_hint(error_type: ErrorType, goal: str) -> str:
    goal_lower = goal.lower()
    # Try specific key first
    for keyword in _HINTS:
        if keyword[0] == error_type and keyword[1] and keyword[1] in goal_lower:
            return _HINTS[keyword]
    # Fall back to generic for this error type
    generic = _HINTS.get((error_type, ""), "")
    return generic or "review the error and try an alternative approach"


class OutcomeInterpreter:
    """Translates a NormalizedResult into semantic meaning relative to a goal."""

    def interpret(self, normalized: NormalizedResult, goal: str) -> InterpretedOutcome:
        """Produce a human-readable outcome with a corrective strategy hint.

        Args:
            normalized: The structured result from ResultNormalizer.
            goal: A short description of what the step was trying to achieve.

        Returns:
            InterpretedOutcome with status, reason, and next_strategy_hint.
        """
        if normalized.success:
            return InterpretedOutcome(
                status="succeeded",
                reason="step completed successfully",
                next_strategy_hint="",
            )

        error_type = normalized.error_type or ErrorType.UNKNOWN
        signal = normalized.signal or "no signal extracted"
        hint = _goal_hint(error_type, goal)

        reason_map = {
            ErrorType.SYNTAX: f"syntax error in tool output: {signal}",
            ErrorType.NOT_FOUND: f"required resource not found: {signal}",
            ErrorType.PERMISSION: f"permission denied: {signal}",
            ErrorType.TIMEOUT: f"operation timed out: {signal}",
            ErrorType.TOOL_FAILURE: f"tool exited with failure: {signal}",
            ErrorType.UNKNOWN: f"unknown failure: {signal}",
        }
        reason = reason_map.get(error_type, f"failure: {signal}")

        return InterpretedOutcome(
            status="failed",
            reason=reason,
            next_strategy_hint=hint,
        )
