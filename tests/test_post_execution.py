"""Tests for the reverse abstraction layer — post-execution pipeline."""

from __future__ import annotations

import pytest

from src.core.models import (
    ErrorType,
    InterpretedOutcome,
    NormalizedResult,
    PlanStep,
    StepFeedback,
    StepStatus,
    ToolResult,
    VerificationResult,
)
from src.core.post_execution.feedback import FeedbackEngine
from src.core.post_execution.interpreter import OutcomeInterpreter
from src.core.post_execution.normalizer import ResultNormalizer
from src.core.post_execution.verifier import VerificationLayer


# ─── ResultNormalizer ─────────────────────────────────────────────────────────


class TestResultNormalizer:
    def setup_method(self):
        self.normalizer = ResultNormalizer()

    def _result(self, success=True, stdout=None, stderr=None, exit_code=None, error=None):
        return ToolResult(
            tool_name="test_tool",
            success=success,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            error=error,
        )

    def test_success_passes_through(self):
        r = self.normalizer.normalize(self._result(success=True))
        assert r.success is True
        assert r.error_type is None

    def test_classifies_syntax_error(self):
        r = self.normalizer.normalize(
            self._result(success=False, stderr="SyntaxError: invalid syntax", exit_code=1)
        )
        assert r.success is False
        assert r.error_type == ErrorType.SYNTAX
        assert "SyntaxError" in r.signal

    def test_classifies_not_found(self):
        r = self.normalizer.normalize(
            self._result(success=False, stderr="No such file or directory: 'foo.py'", exit_code=1)
        )
        assert r.error_type == ErrorType.NOT_FOUND

    def test_classifies_permission_error(self):
        r = self.normalizer.normalize(
            self._result(success=False, stderr="PermissionError: [Errno 13] Permission denied", exit_code=1)
        )
        assert r.error_type == ErrorType.PERMISSION

    def test_classifies_timeout(self):
        r = self.normalizer.normalize(
            self._result(success=False, error="TimeoutError: timed out after 10s", exit_code=None)
        )
        assert r.error_type == ErrorType.TIMEOUT

    def test_nonzero_exit_code_is_tool_failure(self):
        r = self.normalizer.normalize(
            self._result(success=False, stdout="some output", exit_code=2)
        )
        assert r.error_type == ErrorType.TOOL_FAILURE

    def test_raw_fields_preserved(self):
        r = self.normalizer.normalize(
            self._result(success=False, stderr="oops", exit_code=1)
        )
        assert r.raw["tool_name"] == "test_tool"
        assert r.raw["stderr"] == "oops"
        assert r.raw["exit_code"] == 1


# ─── OutcomeInterpreter ───────────────────────────────────────────────────────


class TestOutcomeInterpreter:
    def setup_method(self):
        self.interpreter = OutcomeInterpreter()

    def test_success_returns_succeeded(self):
        n = NormalizedResult(success=True)
        o = self.interpreter.interpret(n, "write a file")
        assert o.status == "succeeded"
        assert o.next_strategy_hint == ""

    def test_not_found_with_write_goal(self):
        n = NormalizedResult(success=False, error_type=ErrorType.NOT_FOUND, signal="foo.txt")
        o = self.interpreter.interpret(n, "write the output to a file")
        assert o.status == "failed"
        assert "not found" in o.reason.lower()
        assert "create" in o.next_strategy_hint.lower() or "directories" in o.next_strategy_hint.lower()

    def test_syntax_error_reason(self):
        n = NormalizedResult(success=False, error_type=ErrorType.SYNTAX, signal="line 5")
        o = self.interpreter.interpret(n, "run python script")
        assert "syntax" in o.reason.lower()

    def test_permission_escalation_hint(self):
        n = NormalizedResult(success=False, error_type=ErrorType.PERMISSION, signal="denied")
        o = self.interpreter.interpret(n, "write config")
        assert "privilege" in o.next_strategy_hint.lower() or "permission" in o.next_strategy_hint.lower() or "ownership" in o.next_strategy_hint.lower()

    def test_unknown_error_fallback(self):
        n = NormalizedResult(success=False, error_type=ErrorType.UNKNOWN, signal="weird error")
        o = self.interpreter.interpret(n, "something")
        assert o.status == "failed"
        assert "unknown" in o.reason.lower()


# ─── VerificationLayer ────────────────────────────────────────────────────────


class TestVerificationLayer:
    def setup_method(self):
        self.verifier = VerificationLayer()

    def _step(self, tool_name=None, tool_args=None):
        return PlanStep(description="test step", tool_name=tool_name, tool_args=tool_args or {})

    def _result(self, success=True, output=None, exit_code=None, error=None):
        return ToolResult(
            tool_name="test_tool",
            success=success,
            output=output,
            exit_code=exit_code,
            error=error,
        )

    def test_failed_result_not_verified(self):
        v = self.verifier.verify(self._step(), self._result(success=False, error="boom"))
        assert v.verified is False
        assert "boom" in v.mismatch

    def test_nonzero_exit_code_fails_process_check(self):
        step = self._step(tool_name="shell_tool", tool_args={"command": "ls"})
        r = self._result(success=True, exit_code=1)
        v = self.verifier.verify(step, r)
        assert v.verified is False
        assert "Non-zero exit code" in v.mismatch

    def test_zero_exit_code_passes_process_check(self):
        step = self._step(tool_name="shell_tool", tool_args={"command": "ls"})
        r = self._result(success=True, exit_code=0)
        v = self.verifier.verify(step, r)
        assert v.verified is True

    def test_python_traceback_fails(self):
        step = self._step(tool_name="python_tool")
        r = ToolResult(
            tool_name="python_tool",
            success=True,
            output="Traceback (most recent call last):\n  ...\nValueError: oops",
            exit_code=0,
        )
        v = self.verifier.verify(step, r)
        assert v.verified is False
        assert "traceback" in v.mismatch.lower()

    def test_web_search_needs_output(self):
        step = self._step(tool_name="web_search_tool")
        r = self._result(success=True, output="")
        v = self.verifier.verify(step, r)
        assert v.verified is False

    def test_web_search_with_output_passes(self):
        step = self._step(tool_name="web_search_tool")
        r = self._result(success=True, output="Results: foo, bar")
        v = self.verifier.verify(step, r)
        assert v.verified is True

    def test_unknown_tool_trusts_success(self):
        step = self._step(tool_name="some_other_tool")
        r = self._result(success=True)
        v = self.verifier.verify(step, r)
        assert v.verified is True


# ─── FeedbackEngine ───────────────────────────────────────────────────────────


class TestFeedbackEngine:
    def setup_method(self):
        self.engine = FeedbackEngine()

    def _step(self, tool_name="file_tool", retry_count=0, max_retries=3, failed_strategies=None):
        return PlanStep(
            description="test step",
            tool_name=tool_name,
            retry_count=retry_count,
            max_retries=max_retries,
            failed_strategies=failed_strategies or [],
        )

    def _parts(self, success=False, error_type=ErrorType.TOOL_FAILURE, signal="error"):
        normalized = NormalizedResult(success=success, error_type=error_type, signal=signal)
        interpreted = InterpretedOutcome(
            status="failed" if not success else "succeeded",
            reason="test reason",
            next_strategy_hint="try something else",
        )
        verified = VerificationResult(verified=success)
        return normalized, interpreted, verified

    def test_verified_returns_done(self):
        step = self._step()
        n = NormalizedResult(success=True)
        i = InterpretedOutcome(status="succeeded", reason="ok")
        v = VerificationResult(verified=True)
        fb = self.engine.build(step, n, i, v)
        assert fb.decision == "done"

    def test_permission_error_escalates(self):
        step = self._step()
        n, i, v = self._parts(error_type=ErrorType.PERMISSION)
        fb = self.engine.build(step, n, i, v)
        assert fb.decision == "escalate"
        assert "file_tool" in fb.constraints

    def test_repeated_strategy_uses_alternative(self):
        step = self._step(failed_strategies=["file_tool"])
        n, i, v = self._parts()
        fb = self.engine.build(step, n, i, v)
        assert fb.decision == "use_alternative_tool"
        assert "file_tool" in fb.constraints

    def test_max_retries_escalates(self):
        step = self._step(retry_count=3, max_retries=3)
        n, i, v = self._parts()
        fb = self.engine.build(step, n, i, v)
        assert fb.decision == "escalate"

    def test_default_is_retry(self):
        step = self._step()
        n, i, v = self._parts()
        fb = self.engine.build(step, n, i, v)
        assert fb.decision == "retry"

    def test_not_found_with_hint_is_retry(self):
        step = self._step()
        n, i, v = self._parts(error_type=ErrorType.NOT_FOUND)
        fb = self.engine.build(step, n, i, v)
        assert fb.decision == "retry"
        assert fb.strategy == "try something else"
