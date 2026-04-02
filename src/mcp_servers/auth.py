"""Simple token-based auth for MCP server."""

from __future__ import annotations

import os
import secrets
import time
from typing import Optional

_TOKENS: dict[str, dict] = {}  # token -> {client_id, created_at, call_count}
_RATE_LIMIT_PER_MIN = 60


def generate_token(client_id: str) -> str:
    """Generate a new auth token for a client."""
    token = secrets.token_urlsafe(32)
    _TOKENS[token] = {"client_id": client_id, "created_at": time.time(), "call_count": 0, "window_start": time.time()}
    return token


def validate_token(token: str) -> tuple[bool, str]:
    """Validate token and check rate limit. Returns (valid, error_message)."""
    if token not in _TOKENS:
        return False, "Invalid token"
    
    entry = _TOKENS[token]
    now = time.time()
    
    # Reset window if > 60s elapsed
    if now - entry["window_start"] >= 60:
        entry["call_count"] = 0
        entry["window_start"] = now
    
    if entry["call_count"] >= _RATE_LIMIT_PER_MIN:
        return False, "Rate limit exceeded: max 60 calls/minute"
    
    entry["call_count"] += 1
    return True, ""


def revoke_token(token: str) -> None:
    """Revoke an auth token."""
    _TOKENS.pop(token, None)
