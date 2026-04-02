"""File system tool for reading, writing, listing, and searching files."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from loguru import logger

from src.core.models import RiskLevel, ToolResult
from src.tools.base import BaseTool


class FileTool(BaseTool):
    """Read, write, list, and search files on disk."""

    name = "file_tool"
    description = "Read, write, list, search files. Safe for read operations."
    risk_level = RiskLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["read", "write", "list", "search", "delete"]},
            "path": {"type": "string", "description": "File or directory path"},
            "content": {"type": "string", "description": "Content to write (for write action)"},
            "pattern": {"type": "string", "description": "Search pattern (for search action)"},
            "dry_run": {"type": "boolean", "default": False},
        },
        "required": ["action", "path"],
    }

    async def validate_args(self, **kwargs: Any) -> tuple[bool, str]:
        """Validate file tool arguments."""
        action = kwargs.get("action", "")
        if action not in ("read", "write", "list", "search", "delete"):
            return False, f"Unknown action: {action}"
        if not kwargs.get("path"):
            return False, "path is required"
        if action == "write" and "content" not in kwargs:
            return False, "content required for write action"
        return True, ""

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the file tool."""
        start = time.monotonic()
        action = kwargs.get("action", "read")
        path_str = kwargs.get("path", "")
        dry_run = kwargs.get("dry_run", False)

        try:
            path = Path(path_str)

            if action == "read":
                if not path.exists():
                    return self._timed_result(start, False, error=f"File not found: {path}")
                content = path.read_text(encoding="utf-8", errors="replace")
                logger.info(f"Read file: {path} ({len(content)} chars)")
                return self._timed_result(start, True, output=content)

            elif action == "write":
                if dry_run:
                    return self._timed_result(start, True, output=f"[dry-run] Would write to {path}")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(kwargs.get("content", ""), encoding="utf-8")
                logger.info(f"Wrote file: {path}")
                return self._timed_result(start, True, output=f"Written: {path}", side_effects=[f"file_written:{path}"])

            elif action == "list":
                if not path.exists():
                    return self._timed_result(start, False, error=f"Path not found: {path}")
                if path.is_file():
                    return self._timed_result(start, True, output=str(path))
                entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
                listing = "\n".join(
                    f"{'[DIR] ' if e.is_dir() else ''}{e.name}" for e in entries
                )
                return self._timed_result(start, True, output=listing or "(empty)")

            elif action == "search":
                pattern = kwargs.get("pattern", "")
                if not pattern:
                    return self._timed_result(start, False, error="pattern required for search")
                results = list(path.rglob(pattern) if path.is_dir() else [path] if path.match(pattern) else [])
                output = "\n".join(str(p) for p in results[:50])
                logger.info(f"Search '{pattern}' in {path}: {len(results)} results")
                return self._timed_result(start, True, output=output or "No matches found")

            elif action == "delete":
                if dry_run:
                    return self._timed_result(start, True, output=f"[dry-run] Would delete {path}")
                if not path.exists():
                    return self._timed_result(start, False, error=f"File not found: {path}")
                path.unlink()
                logger.warning(f"Deleted file: {path}")
                return self._timed_result(start, True, output=f"Deleted: {path}", side_effects=[f"file_deleted:{path}"])

            return self._timed_result(start, False, error=f"Unknown action: {action}")

        except PermissionError as e:
            return self._timed_result(start, False, error=f"Permission denied: {e}")
        except OSError as e:
            return self._timed_result(start, False, error=f"OS error: {e}")
