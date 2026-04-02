"""Token counting utilities for context window management."""

from __future__ import annotations

_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate token count using the 4 chars-per-token heuristic.

    This avoids a hard dependency on tiktoken / OpenAI libraries while
    giving a reasonable approximation for most English prose and code.

    Args:
        text: Input string to measure.

    Returns:
        Estimated token count (minimum 1 for non-empty inputs).
    """
    return max(1, len(text) // _CHARS_PER_TOKEN)


def fits_in_budget(text: str, max_tokens: int) -> bool:
    """Return True if *text* fits within *max_tokens*.

    Args:
        text:       Input string to check.
        max_tokens: Maximum allowed token count (inclusive).

    Returns:
        ``True`` when the estimated token count is ≤ *max_tokens*.
    """
    return estimate_tokens(text) <= max_tokens


def truncate_to_budget(text: str, max_tokens: int) -> str:
    """Truncate *text* so its estimated token count is ≤ *max_tokens*.

    If truncation is required, the returned string ends with ``"..."`` to
    indicate that content was removed.

    Args:
        text:       Input string to truncate.
        max_tokens: Maximum allowed token count.

    Returns:
        Original string (if it fits) or a truncated version ending with
        ``"..."``.
    """
    max_chars = max_tokens * _CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."
