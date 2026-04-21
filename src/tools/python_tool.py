"""Python code execution tool with import sandbox."""

from __future__ import annotations

import ast
import sys
import time
from io import StringIO
from typing import Any

from loguru import logger

from src.core.models import RiskLevel, ToolResult
from src.tools.base import BaseTool
from src.utils.config import load_config

_DEFAULT_ALLOWED_IMPORTS = {"json", "re", "datetime", "math", "os.path", "pathlib", "csv"}
_DEFAULT_TIMEOUT = 30


class PythonTool(BaseTool):
    """Execute sandboxed Python code snippets."""

    name = "python_tool"
    description = "Execute Python code in a sandboxed environment with restricted imports."
    capabilities = ["python_exec", "data_transform", "computation"]
    risk_level = RiskLevel.MODERATE
    parameters_schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "dry_run": {"type": "boolean", "default": False},
        },
        "required": ["code"],
    }

    def _get_allowed_imports(self) -> set[str]:
        try:
            cfg = load_config("tools")
            imports = cfg.get("tools", {}).get("python_tool", {}).get("sandbox", {}).get("allowed_imports", [])
            return set(imports) if imports else _DEFAULT_ALLOWED_IMPORTS
        except Exception:
            return _DEFAULT_ALLOWED_IMPORTS

    def _check_imports(self, code: str) -> tuple[bool, str]:
        """Parse code AST and check for disallowed imports."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"Syntax error: {e}"

        allowed = self._get_allowed_imports()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = alias.name.split(".")[0]
                    if base not in allowed and alias.name not in allowed:
                        return False, f"Import not allowed: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                base = module.split(".")[0]
                if base not in allowed and module not in allowed:
                    return False, f"Import not allowed: {module}"
        return True, ""

    async def validate_args(self, **kwargs: Any) -> tuple[bool, str]:
        code = kwargs.get("code", "")
        if not code.strip():
            return False, "code is required"
        return self._check_imports(code)

    async def execute(self, **kwargs: Any) -> ToolResult:
        start = time.monotonic()
        code = kwargs.get("code", "").strip()
        dry_run = kwargs.get("dry_run", False)

        if dry_run:
            return self._timed_result(start, True, output=f"[dry-run] Would execute Python code ({len(code)} chars)")

        try:
            stdout_buf = StringIO()
            old_stdout = sys.stdout
            sys.stdout = stdout_buf

            local_vars: dict = {}
            # Restrict builtins to a safe subset to prevent bypassing import sandbox
            safe_builtins = {
                "print": print,
                "len": len,
                "range": range,
                "enumerate": enumerate,
                "zip": zip,
                "map": map,
                "filter": filter,
                "sorted": sorted,
                "reversed": reversed,
                "list": list,
                "dict": dict,
                "set": set,
                "tuple": tuple,
                "str": str,
                "int": int,
                "float": float,
                "bool": bool,
                "type": type,
                "isinstance": isinstance,
                "hasattr": hasattr,
                "getattr": getattr,
                "setattr": setattr,
                "repr": repr,
                "abs": abs,
                "max": max,
                "min": min,
                "sum": sum,
                "round": round,
                "any": any,
                "all": all,
            }
            try:
                exec(compile(code, "<agent>", "exec"), {"__builtins__": safe_builtins}, local_vars)  # noqa: S102
                output = stdout_buf.getvalue()
                if not output and local_vars:
                    output = str({k: v for k, v in local_vars.items() if not k.startswith("_")})
                logger.info("Python code executed successfully")
                return self._timed_result(start, True, output=output or "(no output)")
            except Exception as e:
                return self._timed_result(start, False, error=f"Runtime error: {type(e).__name__}: {e}")
            finally:
                sys.stdout = old_stdout
        except Exception as e:
            return self._timed_result(start, False, error=f"Execution error: {e}")
