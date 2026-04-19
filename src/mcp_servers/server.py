"""MCP server exposing the agent to Claude Code/Cline via WebSocket on port 8765."""

from __future__ import annotations

import asyncio
import json

from loguru import logger

from src.mcp_servers.auth import generate_token, validate_token
from src.mcp_servers.handlers import (
    handle_execute_tool,
    handle_get_status,
    handle_list_tools,
    handle_submit_task,
)


class MCPServer:
    """WebSocket-based MCP server for agent access."""

    def __init__(self, host: str = "localhost", port: int = 8765, agent=None) -> None:
        self.host = host
        self.port = port
        self._agent = agent
        self._server = None

    async def start(self) -> None:
        """Start the MCP WebSocket server."""
        try:
            import websockets
            self._server = await websockets.serve(
                self._handle_client,
                self.host,
                self.port,
            )
            logger.info(f"MCP server listening on ws://{self.host}:{self.port}")
        except ImportError:
            logger.error("websockets package not installed — MCP server disabled")
        except Exception as e:
            logger.error(f"MCP server failed to start: {e}")

    async def _handle_client(self, websocket, path: str = "/") -> None:
        """Handle a single MCP client connection."""
        token = generate_token(f"client-{id(websocket)}")
        logger.info(f"MCP client connected from {websocket.remote_address}")

        try:
            async for message in websocket:
                await self._process_message(websocket, token, message)
        except Exception as e:
            logger.warning(f"MCP client disconnected: {e}")
        finally:
            logger.info("MCP client disconnected")

    async def _process_message(self, websocket, token: str, raw: str) -> None:
        """Process a single MCP message."""
        valid, error = validate_token(token)
        if not valid:
            response = {"error": error}
            asyncio.create_task(websocket.send(json.dumps(response)))
            return

        try:
            msg = json.loads(raw)
            method = msg.get("method", "")
            params = msg.get("params", {})
            msg_id = msg.get("id")

            result = await self._dispatch(method, params)
            response = {"id": msg_id, "result": result}
        except json.JSONDecodeError:
            response = {"error": "Invalid JSON"}
        except Exception as e:
            logger.error(f"MCP message error: {e}")
            response = {"error": str(e)}

        asyncio.create_task(websocket.send(json.dumps(response)))

    async def _dispatch(self, method: str, params: dict) -> dict:
        """Dispatch MCP method to handler."""
        if method == "list_tools":
            return await handle_list_tools(self._agent)
        elif method == "execute_tool":
            return await handle_execute_tool(
                self._agent,
                params.get("tool_name", ""),
                params.get("args", {}),
            )
        elif method == "get_status":
            return await handle_get_status(self._agent)
        elif method == "submit_task":
            return await handle_submit_task(
                self._agent,
                params.get("text", ""),
                params.get("source", "mcp"),
            )
        else:
            return {"error": f"Unknown method: {method}"}

    async def stop(self) -> None:
        """Stop the MCP server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("MCP server stopped")
