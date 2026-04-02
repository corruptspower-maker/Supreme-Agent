"""Tests for src/utils/lm_studio_client.py."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


class TestLMStudioClientHealthCheck:
    async def test_returns_false_when_server_unavailable(self):
        """health_check returns False if connection refused."""
        from src.utils.lm_studio_client import LMStudioClient
        
        client = LMStudioClient(endpoint="http://localhost:19999/v1", timeout=2.0)
        result = await client.health_check()
        assert result is False

    async def test_returns_true_when_server_ok(self):
        """health_check returns True when server returns 200."""
        from src.utils.lm_studio_client import LMStudioClient
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        
        with patch("httpx.AsyncClient") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_class.return_value = mock_instance
            
            client = LMStudioClient()
            result = await client.health_check()
        assert result is True

    async def test_returns_false_on_exception(self):
        """health_check returns False on any exception."""
        from src.utils.lm_studio_client import LMStudioClient
        
        with patch("httpx.AsyncClient") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_instance.get = AsyncMock(side_effect=Exception("network error"))
            mock_class.return_value = mock_instance
            
            client = LMStudioClient()
            result = await client.health_check()
        assert result is False


class TestLMStudioClientComplete:
    async def test_raises_runtime_error_without_context_manager(self):
        """complete() raises RuntimeError if not used as context manager."""
        from src.utils.lm_studio_client import LMStudioClient
        
        client = LMStudioClient()
        with pytest.raises(RuntimeError, match="async context manager"):
            await client.complete([{"role": "user", "content": "hi"}])

    async def test_timeout_raises_timeout_error(self):
        """TimeoutError is raised on asyncio timeout."""
        import asyncio
        from src.utils.lm_studio_client import LMStudioClient
        
        async with LMStudioClient() as client:
            mock_post = AsyncMock(side_effect=asyncio.TimeoutError())
            client._client.post = mock_post
            
            with pytest.raises(TimeoutError, match="timeout"):
                await client.complete([{"role": "user", "content": "hi"}])

    async def test_http_error_raises_runtime_error(self):
        """HTTP errors are wrapped in RuntimeError."""
        from src.utils.lm_studio_client import LMStudioClient
        
        async with LMStudioClient() as client:
            mock_post = AsyncMock(side_effect=httpx.HTTPError("bad request"))
            client._client.post = mock_post
            
            with pytest.raises(RuntimeError, match="HTTP error"):
                await client.complete([{"role": "user", "content": "hi"}])


class TestLMStudioClientCompleteJson:
    async def test_parses_valid_json_response(self):
        """complete_json returns parsed dict on valid JSON response."""
        from src.utils.lm_studio_client import LMStudioClient
        
        expected = {"key": "value", "number": 42}
        
        async with LMStudioClient() as client:
            client.complete = AsyncMock(return_value=json.dumps(expected))
            result = await client.complete_json([{"role": "user", "content": "hi"}])
        
        assert result == expected

    async def test_strips_markdown_code_fences(self):
        """JSON wrapped in ```json code fences is parsed correctly."""
        from src.utils.lm_studio_client import LMStudioClient
        
        fenced = '```json\n{"key": "value"}\n```'
        
        async with LMStudioClient() as client:
            client.complete = AsyncMock(return_value=fenced)
            result = await client.complete_json([{"role": "user", "content": "hi"}])
        
        assert result == {"key": "value"}

    async def test_retries_on_json_parse_failure(self):
        """Retries up to 3 times on JSON parse failure."""
        from src.utils.lm_studio_client import LMStudioClient
        
        call_count = 0
        
        async def fake_complete(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return "not valid json"
            return '{"success": true}'
        
        async with LMStudioClient() as client:
            client.complete = fake_complete
            result = await client.complete_json([{"role": "user", "content": "hi"}])
        
        assert result == {"success": True}
        assert call_count == 3

    async def test_raises_after_3_failures(self):
        """RuntimeError raised after 3 failed JSON parse attempts."""
        from src.utils.lm_studio_client import LMStudioClient
        
        async with LMStudioClient() as client:
            client.complete = AsyncMock(return_value="this is not json at all!!!")
            
            with pytest.raises(RuntimeError, match="unparseable response after 3 attempts"):
                await client.complete_json([{"role": "user", "content": "hi"}])

    async def test_timeout_propagates_without_retry(self):
        """TimeoutError does not get retried — propagates immediately."""
        from src.utils.lm_studio_client import LMStudioClient
        
        call_count = 0
        
        async def fake_complete(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            raise TimeoutError("timed out")
        
        async with LMStudioClient() as client:
            client.complete = fake_complete
            
            with pytest.raises(TimeoutError):
                await client.complete_json([{"role": "user", "content": "hi"}])
        
        assert call_count == 1


class TestGetLMStudioClient:
    async def test_factory_returns_client(self):
        """get_lm_studio_client returns a configured LMStudioClient."""
        from src.utils.lm_studio_client import LMStudioClient, get_lm_studio_client
        
        client = await get_lm_studio_client()
        assert isinstance(client, LMStudioClient)
        assert "localhost" in client.endpoint or "1234" in client.endpoint
