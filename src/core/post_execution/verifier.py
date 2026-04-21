"""VerificationLayer — confirms that reality matches intent after a step executes."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from loguru import logger

from src.core.models import PlanStep, ToolResult, VerificationResult


class VerificationLayer:
    """Checks post-execution reality against what the step intended."""

    def verify(self, step: PlanStep, result: ToolResult) -> VerificationResult:
        """Verify that *step*'s effects were actually realized.

        Dispatches to a per-tool-type checker.  Falls back to a generic
        exit-code check when no specific checker exists.
        """
        if not result.success:
            # Already failed — no point verifying side-effects
            return VerificationResult(
                verified=False,
                mismatch=result.error or "tool reported failure",
            )

        tool = step.tool_name or ""

        try:
            if tool == "file_tool":
                return self._verify_file(step, result)
            if tool == "screenshot_tool":
                return self._verify_screenshot(step, result)
            if tool in ("shell_tool", "python_tool"):
                return self._verify_process(result)
            if tool == "web_search_tool":
                return self._verify_has_output(result)
            # Generic: trust success flag
            return VerificationResult(verified=True)
        except Exception as exc:
            logger.warning(f"Verification raised unexpectedly for {tool}: {exc}")
            return VerificationResult(verified=False, mismatch=str(exc))

    # ─── Per-tool checks ──────────────────────────────────────────────────────

    def _verify_file(self, step: PlanStep, result: ToolResult) -> VerificationResult:
        """After a file_tool write, check the file exists and is non-empty."""
        action = step.tool_args.get("action", "")
        path_str: Optional[str] = step.tool_args.get("path") or step.tool_args.get("file_path")

        if action not in ("write", "append", "create") or not path_str:
            return VerificationResult(verified=True)

        path = Path(path_str)
        if not path.exists():
            return VerificationResult(
                verified=False,
                mismatch=f"Expected file not found: {path}",
            )
        if path.stat().st_size == 0:
            return VerificationResult(
                verified=False,
                mismatch=f"File exists but is empty: {path}",
            )
        return VerificationResult(verified=True)

    def _verify_screenshot(self, step: PlanStep, result: ToolResult) -> VerificationResult:
        """After a screenshot_tool call, confirm the image file was created."""
        output = result.output or ""
        # Output typically contains the saved path
        for token in output.split():
            p = Path(token)
            if p.suffix.lower() in (".png", ".jpg", ".jpeg") and p.exists():
                return VerificationResult(verified=True)

        # Fallback: check tool_args for an explicit path
        path_str = step.tool_args.get("path") or step.tool_args.get("filename")
        if path_str:
            p = Path(path_str)
            if p.exists():
                return VerificationResult(verified=True)
            return VerificationResult(verified=False, mismatch=f"Screenshot file not found: {p}")

        # Can't determine path from output; trust success flag
        return VerificationResult(verified=True)

    def _verify_process(self, result: ToolResult) -> VerificationResult:
        """Shell/Python tool: verify exit_code is 0 and no traceback in output."""
        if result.exit_code is not None and result.exit_code != 0:
            return VerificationResult(
                verified=False,
                mismatch=f"Non-zero exit code: {result.exit_code}",
            )
        output = (result.stdout or "") + (result.output or "")
        if "Traceback (most recent call last)" in output:
            lines = [l for l in output.splitlines() if l.strip()]
            last_line = lines[-1] if lines else "unknown error"
            return VerificationResult(
                verified=False,
                mismatch=f"Python traceback detected: {last_line}",
            )
        return VerificationResult(verified=True)

    def _verify_has_output(self, result: ToolResult) -> VerificationResult:
        """Generic: check that the tool produced some non-empty output."""
        has_output = bool(result.output and result.output.strip())
        if not has_output:
            return VerificationResult(verified=False, mismatch="Tool produced no output")
        return VerificationResult(verified=True)
