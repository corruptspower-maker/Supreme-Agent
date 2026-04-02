"""Shell command tool with whitelist-based sandboxing."""

from __future__ import annotations

import asyncio
import shlex
import time
from typing import Any

from loguru import logger

from src.core.models import RiskLevel, ToolResult
from src.tools.base import BaseTool
from src.utils.config import load_config

_DEFAULT_ALLOWED = {"dir", "type", "findstr", "echo", "date", "whoami", "ping"}
_DEFAULT_TIMEOUT = 10


class ShellTool(BaseTool):
    """Execute whitelisted shell commands safely."""

    name = "shell_tool"
    description = "Execute whitelisted shell commands. Requires confirmation."
    risk_level = RiskLevel.DANGEROUS
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run"},
            "dry_run": {"type": "boolean", "default": False},
        },
        "required": ["command"],
    }

    def _get_allowed(self) -> set[str]:
        try:
            cfg = load_config("tools")
            cmds = cfg.get("tools", {}).get("shell_tool", {}).get("sandbox", {}).get("allowed_commands", [])
            return set(cmds) if cmds else _DEFAULT_ALLOWED
        except Exception:
            return _DEFAULT_ALLOWED

    def _get_timeout(self) -> int:
        try:
            cfg = load_config("tools")
            return int(cfg.get("tools", {}).get("shell_tool", {}).get("sandbox", {}).get("timeout_seconds", _DEFAULT_TIMEOUT))
        except Exception:
            return _DEFAULT_TIMEOUT

    async def validate_args(self, **kwargs: Any) -> tuple[bool, str]:
        command = kwargs.get("command", "").strip()
        if not command:
            return False, "command is required"
        cmd_name = shlex.split(command)[0].lower() if command else ""
        allowed = self._get_allowed()
        if cmd_name not in allowed:
            return False, f"Command '{cmd_name}' not in whitelist: {sorted(allowed)}"
        return True, ""

    async def execute(self, **kwargs: Any) -> ToolResult:
        start = time.monotonic()
        command = kwargs.get("command", "").strip()
        dry_run = kwargs.get("dry_run", False)

        if dry_run:
            return self._timed_result(start, True, output=f"[dry-run] Would execute: {command}")

        try:
            timeout = self._get_timeout()
            args = shlex.split(command)
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode(errors="replace").strip()
            err_output = stderr.decode(errors="replace").strip()
            success = proc.returncode == 0
            combined = output + ("\n" + err_output if err_output else "")
            logger.info(f"Shell command {'succeeded' if success else 'failed'}: {command}")
            return self._timed_result(start, success, output=combined or "(no output)", side_effects=[f"shell_executed:{command}"])
        except asyncio.TimeoutError:
            return self._timed_result(start, False, error=f"Command timed out after {self._get_timeout()}s")
        except OSError as e:
            return self._timed_result(start, False, error=f"OS error: {e}")
