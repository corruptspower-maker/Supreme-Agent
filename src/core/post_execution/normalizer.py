"""ResultNormalizer — converts raw ToolResult into structured NormalizedResult.

Classifies errors using the standard ErrorType taxonomy:
  SYNTAX, NOT_FOUND, PERMISSION, TIMEOUT, TOOL_FAILURE, UNKNOWN
"""

from __future__ import annotations

import re
from typing import Optional

from src.core.models import ErrorType, NormalizedResult, ToolResult

# ─── Keyword → ErrorType mappings ────────────────────────────────────────────

_SYNTAX_PATTERNS = re.compile(
    r"SyntaxError|IndentationError|ParseError|unexpected token"
    r"|invalid syntax|missing.*parenthes|unexpected EOF",
    re.IGNORECASE,
)

_NOT_FOUND_PATTERNS = re.compile(
    r"No such file or directory|FileNotFoundError|ModuleNotFoundError"
    r"|command not found|cannot find|not found|ENOENT",
    re.IGNORECASE,
)

_PERMISSION_PATTERNS = re.compile(
    r"PermissionError|Permission denied|EACCES|Access is denied"
    r"|Operation not permitted|not authorized",
    re.IGNORECASE,
)

_TIMEOUT_PATTERNS = re.compile(
    r"TimeoutError|timed out|timeout|ETIMEDOUT|ReadTimeout|ConnectTimeout",
    re.IGNORECASE,
)


def _extract_signal(text: str) -> str:
    """Return the first non-empty, meaningful line from noisy output."""
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:200]
    return text[:200]


def _classify(stdout: Optional[str], stderr: Optional[str], exit_code: Optional[int], error: Optional[str]) -> tuple[ErrorType, str]:
    """Classify error type and extract signal from raw tool output."""
    combined = " ".join(filter(None, [stderr, error, stdout]))

    if not combined and (exit_code is None or exit_code == 0):
        return ErrorType.UNKNOWN, ""

    signal = _extract_signal(stderr or error or stdout or "")

    if _SYNTAX_PATTERNS.search(combined):
        return ErrorType.SYNTAX, signal
    if _NOT_FOUND_PATTERNS.search(combined):
        return ErrorType.NOT_FOUND, signal
    if _PERMISSION_PATTERNS.search(combined):
        return ErrorType.PERMISSION, signal
    if _TIMEOUT_PATTERNS.search(combined):
        return ErrorType.TIMEOUT, signal
    if exit_code is not None and exit_code != 0:
        return ErrorType.TOOL_FAILURE, signal

    return ErrorType.UNKNOWN, signal


class ResultNormalizer:
    """Converts raw ToolResult into a structured NormalizedResult."""

    def normalize(self, result: ToolResult) -> NormalizedResult:
        """Normalize *result* into a consistent schema.

        Returns:
            NormalizedResult with success flag, classified error_type,
            extracted signal, and the original fields preserved in raw.
        """
        raw = {
            "tool_name": result.tool_name,
            "output": result.output,
            "error": result.error,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "execution_time_ms": result.execution_time_ms,
        }

        if result.success:
            return NormalizedResult(success=True, raw=raw)

        error_type, signal = _classify(
            result.stdout,
            result.stderr,
            result.exit_code,
            result.error,
        )

        return NormalizedResult(
            success=False,
            error_type=error_type,
            signal=signal,
            raw=raw,
        )
