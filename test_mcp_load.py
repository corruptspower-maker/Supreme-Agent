#!/usr/bin/env python3
import sys
sys.path.insert(0, 'src')

from mcp_servers.lmstudio_exposer import mcp

print("MCP loaded successfully")
print(f"Server name: {mcp.name}")
print("Server is ready!")
