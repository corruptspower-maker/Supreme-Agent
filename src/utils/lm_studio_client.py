"""Async LM Studio client using httpx."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional, AsyncIterator

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.utils.config import load_config


class LMStudioClient:
    """Async client for LM Studio's OpenAI-compatible API."""

    def __init__(self, endpoint: str = "http://localhost:1234/v1", timeout: float = 120.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "LMStudioClient":
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    async def health_check(self) -> bool:
        """Check if LM Studio is running and accessible."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{self.endpoint}/models")
                return r.status_code == 200
        except Exception:
            return False

    async def complete(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
    ) -> str:
        """
        Send a chat completion request to LM Studio.
        Returns the assistant message content string.
        Raises RuntimeError on failure.
        """
        cfg = load_config("models")
        model_name = model or cfg.get("local", {}).get("primary", {}).get("name", "")
        
        if self._client is None:
            raise RuntimeError("LMStudioClient must be used as async context manager")
        
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        
        try:
            response = await asyncio.wait_for(
                self._client.post(f"{self.endpoint}/chat/completions", json=payload),
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except asyncio.TimeoutError as e:
            raise TimeoutError(f"LM Studio timeout after {self.timeout}s") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"LM Studio HTTP error: {e}") from e

    async def complete_json(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> dict:
        """
        Complete and parse JSON response.
        Retries 3 times on parse failure with 'Respond with valid JSON only.' appended.
        """
        working_messages = list(messages)
        last_error: Exception = RuntimeError("No response")
        raw = ""
        
        for attempt in range(3):
            try:
                raw = await self.complete(working_messages, model=model, temperature=temperature, max_tokens=max_tokens)
                # Strip markdown code fences if present
                cleaned = raw.strip()
                if cleaned.startswith("```"):
                    lines = cleaned.split("\n")
                    cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
                return json.loads(cleaned)
            except (json.JSONDecodeError, KeyError) as e:
                last_error = e
                logger.warning(f"LM Studio JSON parse failure (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    working_messages = list(messages) + [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": "Respond with valid JSON only. Previous response could not be parsed."},
                    ]
            except (TimeoutError, RuntimeError):
                raise
        
        raise RuntimeError(f"local model returned unparseable response after 3 attempts: {last_error}")


async def get_lm_studio_client() -> LMStudioClient:
    """Factory: create a configured LM Studio client."""
    cfg = load_config("models")
    endpoint = cfg.get("local", {}).get("primary", {}).get("endpoint", "http://localhost:1234/v1")
    timeout = cfg.get("local", {}).get("primary", {}).get("timeout_seconds", 120)
    return LMStudioClient(endpoint=endpoint, timeout=float(timeout))
