"""Web search tool using DuckDuckGo (no API key required)."""

from __future__ import annotations

import time
from typing import Any

import httpx
from loguru import logger

from src.core.models import RiskLevel, ToolResult
from src.tools.base import BaseTool


class WebSearchTool(BaseTool):
    """Search the web using DuckDuckGo Instant Answers API."""

    name = "web_search_tool"
    description = "Search the web for information. Returns top results."
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

    async def validate_args(self, **kwargs: Any) -> tuple[bool, str]:
        if not kwargs.get("query", "").strip():
            return False, "query is required"
        return True, ""

    async def execute(self, **kwargs: Any) -> ToolResult:
        start = time.monotonic()
        query = kwargs.get("query", "").strip()
        dry_run = kwargs.get("dry_run", False)

        if dry_run:
            return self._timed_result(start, True, output=f"[dry-run] Would search for: {query}")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": "1", "no_redirect": "1"},
                )
                response.raise_for_status()
                data = response.json()

                results = []
                abstract = data.get("AbstractText", "")
                if abstract:
                    results.append(f"Summary: {abstract}")

                related = data.get("RelatedTopics", [])[:5]
                for item in related:
                    if isinstance(item, dict) and "Text" in item:
                        results.append(item["Text"])

                output = "\n".join(results) if results else f"No results found for: {query}"
                logger.info(f"Web search: '{query}' → {len(results)} results")
                return self._timed_result(start, True, output=output)

        except httpx.TimeoutException:
            return self._timed_result(start, False, error="Web search timed out")
        except httpx.HTTPError as e:
            return self._timed_result(start, False, error=f"HTTP error: {e}")
        except Exception as e:
            return self._timed_result(start, False, error=f"Search failed: {e}")
