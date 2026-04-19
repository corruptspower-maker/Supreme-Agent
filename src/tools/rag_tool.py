"""RAG tool — retrieval-augmented generation using ChromaDB."""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from src.core.models import RiskLevel, ToolResult
from src.tools.base import BaseTool


class RAGTool(BaseTool):
    """Search semantic memory using RAG. Returns relevant stored knowledge."""

    name = "rag_tool"
    description = "Search stored knowledge using semantic similarity. Safe, read-only."
    risk_level = RiskLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "default": 5},
            "dry_run": {"type": "boolean", "default": False},
        },
        "required": ["query"],
    }

    def __init__(self, memory_manager=None) -> None:
        self._memory = memory_manager

    async def validate_args(self, **kwargs: Any) -> tuple[bool, str]:
        if not kwargs.get("query", "").strip():
            return False, "query is required"
        return True, ""

    async def execute(self, **kwargs: Any) -> ToolResult:
        start = time.monotonic()
        query = kwargs.get("query", "").strip()
        dry_run = kwargs.get("dry_run", False)

        if dry_run:
            return self._timed_result(start, True, output=f"[dry-run] Would search memory for: {query}")

        if self._memory is None:
            return self._timed_result(start, False, error="Memory manager not available")

        try:
            result = await self._memory.search(query)
            logger.info(f"RAG search: '{query}'")
            return self._timed_result(start, True, output=result or "No relevant memories found")
        except Exception as e:
            return self._timed_result(start, False, error=f"RAG search failed: {e}")
