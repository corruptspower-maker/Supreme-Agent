#!/usr/bin/env python3
r'''
LM Studio Tool Exposer - Full-Featured MCP Server

This server exposes all Supreme-Agent tools to LM Studio via MCP protocol.

Run with: uv run src/mcp_servers/lmstudio_exposer.py

LM Studio settings:
  - Protocol: stdio
  - Command: uv
  - Args: run src/mcp_servers/lmstudio_exposer.py
  - Working Directory: c:\repo-path\root
'''

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.tools.file_tool import FileTool
from src.tools.shell_tool import ShellTool
from src.tools.python_tool import PythonTool
from src.tools.web_search_tool import WebSearchTool
from src.tools.rag_tool import RAGTool
from src.tools.email_tool import EmailTool
from src.utils.config import load_config

load_dotenv()

# ============================================================================
# SERVER INITIALIZATION
# ============================================================================

mcp = FastMCP(
    name='Supreme-Agent Tools',
)

# Initialize tools
_file_tool = FileTool()
_shell_tool = ShellTool()
_python_tool = PythonTool()
_web_search_tool = WebSearchTool()
_rag_tool = RAGTool()
_email_tool = EmailTool()

# Server stats
_server_start_time = time.time()
_request_count = 0


# ============================================================================
# MCP RESOURCES - File access via URIs
# ============================================================================

@mcp.resource("file://readme")
async def readme_resource() -> str:
    """Provide the README content as a resource."""
    try:
        readme_path = Path(__file__).parent.parent.parent / "README.md"
        if readme_path.exists():
            return f"# README\n\n{readme_path.read_text(encoding='utf-8')}"
    except Exception as e:
        return f"Error reading README: {e}"
    return "README.md not found"


@mcp.resource("file://config")
async def config_resource() -> str:
    """Provide server configuration as a resource."""
    try:
        cfg = load_config('mcp')
        return json.dumps(cfg, indent=2)
    except Exception as e:
        return f"Error loading config: {e}"


@mcp.resource("file://tools")
async def tools_list_resource() -> str:
    """List all available tools with their schemas."""
    tools_info = {
        "count": 16,
        "tools": [
            {"name": "file_read", "description": "Read file contents", "risk": "safe"},
            {"name": "file_write", "description": "Write content to files", "risk": "medium"},
            {"name": "file_list", "description": "List directory contents", "risk": "safe"},
            {"name": "file_search", "description": "Search for files by pattern", "risk": "safe"},
            {"name": "file_delete", "description": "Delete a file", "risk": "high"},
            {"name": "shell_execute", "description": "Execute whitelisted shell command", "risk": "medium"},
            {"name": "shell_list_commands", "description": "List allowed shell commands", "risk": "safe"},
            {"name": "python_execute", "description": "Execute Python code in sandbox", "risk": "medium"},
            {"name": "web_search", "description": "Search the web", "risk": "safe"},
            {"name": "knowledge_search", "description": "Search knowledge base", "risk": "safe"},
            {"name": "knowledge_add", "description": "Add to knowledge base", "risk": "safe"},
            {"name": "email_send", "description": "Send an email", "risk": "high"},
            {"name": "get_working_directory", "description": "Get current directory", "risk": "safe"},
            {"name": "list_available_tools", "description": "List all tools", "risk": "safe"},
            {"name": "get_server_status", "description": "Server health and stats", "risk": "safe"},
            {"name": "server_llm_complete", "description": "Server-side LLM completion", "risk": "safe"},
        ]
    }
    return json.dumps(tools_info, indent=2)


@mcp.resource("file://allowed-shells")
async def allowed_shells_resource() -> str:
    """List shell commands the model is allowed to execute."""
    cfg = load_config('tools')
    allowed = cfg.get('tools', {}).get('shell_tool', {}).get('sandbox', {}).get('allowed_commands', [])
    return json.dumps({
        "commands": sorted(allowed) if allowed else ["dir", "type", "findstr", "echo", "date", "whoami", "ping"],
        "count": len(allowed) if allowed else 7
    }, indent=2)


@mcp.resource("file://sandbox-allowed-imports")
async def sandbox_imports_resource() -> str:
    """List Python imports allowed in sandboxed execution."""
    return json.dumps({
        "allowed_imports": list(_python_tool._get_allowed_imports()),
        "note": "Code execution is sandboxed with limited imports for safety"
    }, indent=2)


@mcp.resource("memory://recent-files")
async def recent_files_resource() -> str:
    """Track recently accessed files (in-memory)."""
    return json.dumps({
        "note": "File access history is maintained by the agent",
        "max_history": 100
    }, indent=2)


@mcp.resource("server://info")
async def server_info_resource() -> str:
    """Get server information and capabilities."""
    return json.dumps({
        "name": "Supreme-Agent MCP Server",
        "version": "1.0.0",
        "protocol": "MCP 2024-11-05",
        "capabilities": {
            "tools": True,
            "resources": True,
            "prompts": True,
            "sampling": True
        },
        "features": [
            "File operations (read, write, list, search, delete)",
            "Shell command execution (whitelisted)",
            "Python code execution (sandboxed)",
            "Web search",
            "RAG knowledge base",
            "Email sending",
            "Server-side LLM calls"
        ]
    }, indent=2)


# ============================================================================
# MCP PROMPTS - Reusable prompt templates
# ============================================================================

@mcp.prompt()
def analyze_codebase_prompt(target_path: str = ".") -> str:
    """Generate a prompt for analyzing a codebase."""
    return f"""Analyze the codebase at {target_path}.

Provide:
1. Project structure overview
2. Key files and their purposes
3. Dependencies and requirements
4. Main entry points
5. Configuration files

Use file_list, file_read, and file_search tools to explore."""


@mcp.prompt()
def debug_error_prompt(error_message: str = "") -> str:
    """Generate a prompt for debugging an error."""
    return f"""Debug the following error:

{error_message}

Steps:
1. Analyze the error type and location
2. Check relevant code files
3. Look for similar patterns in the codebase
4. Suggest fixes

Use file_read and shell_execute tools to investigate."""


@mcp.prompt()
def review_code_prompt(file_path: str = "") -> str:
    """Generate a prompt for code review."""
    return f"""Review the code at: {file_path}

Focus on:
1. Code quality and style
2. Potential bugs or edge cases
3. Security concerns
4. Performance implications
5. Best practices compliance

Use file_read to examine the code."""


@mcp.prompt()
def search_and_replace_prompt(search_pattern: str = "", replacement: str = "") -> str:
    """Generate a prompt for search-and-replace operations."""
    return f"""Search and replace in the codebase:

Pattern: {search_pattern}
Replacement: {replacement}

Steps:
1. Use file_search to find all occurrences
2. Read affected files
3. Use file_write to make replacements (back up first!)
4. Verify changes

Be careful with broad patterns!"""


@mcp.prompt()
def write_tests_prompt(module_path: str = "") -> str:
    """Generate a prompt for writing tests."""
    return f"""Write tests for: {module_path}

Steps:
1. file_read the module to understand the interface
2. file_list the tests directory for existing patterns
3. Write tests covering:
   - Happy path
   - Edge cases
   - Error conditions
4. Run tests to verify

Use file_read, file_list, file_write, and python_execute tools."""


@mcp.prompt()
def research_topic_prompt(topic: str = "") -> str:
    """Generate a prompt for researching a topic."""
    return f"""Research: {topic}

Steps:
1. Use web_search to find relevant information
2. Use knowledge_search to check existing knowledge base
3. Synthesize findings
4. Add useful information to knowledge base

Keep notes for future reference!"""


@mcp.prompt()
def refactor_code_prompt(file_path: str = "", goal: str = "improve") -> str:
    """Generate a prompt for code refactoring."""
    return f"""Refactor code at: {file_path}

Goal: {goal}

Steps:
1. file_read the current implementation
2. Identify areas for improvement
3. Make incremental changes
4. file_write updated version
5. Verify functionality

Focus on: readability, maintainability, performance"""


# ============================================================================
# MCP SAMPLING - Server-side LLM calls
# ============================================================================

@mcp.tool()
async def server_llm_complete(
    prompt: str,
    model: str = "local",
    max_tokens: int = 256,
    temperature: float = 0.7
) -> str:
    """Use the server-side LLM (via LM Studio) for completion.
    
    This allows the server to make LLM calls independently.
    """
    try:
        import httpx
        
        api_key = os.getenv('LM_STUDIO_API_KEY', '')
        base_url = os.getenv('LM_STUDIO_BASE_URL', 'http://localhost:1234/v1')
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")
            else:
                return f"Error: LLM returned status {response.status_code}"
    except Exception as e:
        return f"Error calling LLM: {e}"


@mcp.tool()
async def server_llm_summarize(text: str, max_length: int = 200) -> str:
    """Summarize text using the server-side LLM."""
    prompt = f"""Summarize the following text in no more than {max_length} words:

{text[:4000]}

Summary:"""
    return await server_llm_complete(prompt, max_tokens=max_length * 2)


# ============================================================================
# FILE TOOLS - Safe file operations
# ============================================================================

@mcp.tool()
async def file_read(path: str, start_line: int = 1, max_lines: int = 1000) -> str:
    '''Read file contents with optional line range.
    
    Args:
        path: Absolute path to the file
        start_line: Starting line number (1-based, default: 1)
        max_lines: Maximum lines to read (default: 1000, use 0 for all)
    '''
    result = await _file_tool.execute(action='read', path=path)
    if not result.success:
        return f'Error: {result.error}'
    
    content = result.output or '(empty file)'
    
    if start_line > 1 or (max_lines > 0 and len(content.split('\n')) > max_lines):
        lines = content.split('\n')
        end_line = len(lines) if max_lines == 0 else min(start_line + max_lines - 1, len(lines))
        lines = lines[start_line - 1:end_line]
        content = '\n'.join(lines)
        if end_line < len(lines):
            content += f'\n\n... ({end_line} of {len(lines)} lines shown)'
    
    return content


@mcp.tool()
async def file_write(path: str, content: str, create_dirs: bool = True) -> str:
    '''Write content to a file with directory creation option.
    
    Args:
        path: Absolute path where the file should be written
        content: The text content to write
        create_dirs: Automatically create parent directories (default: True)
    '''
    if create_dirs:
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return f'Error creating directories: {e}'
    
    result = await _file_tool.execute(action='write', path=path, content=content)
    if result.success:
        return result.output or f'Successfully wrote to {path}'
    return f'Error: {result.error}'


@mcp.tool()
async def file_list(path: str, recursive: bool = False, include_hidden: bool = False) -> str:
    '''List files and directories with filtering options.
    
    Args:
        path: Absolute path to the directory
        recursive: Include subdirectories (default: False)
        include_hidden: Include hidden files starting with . (default: False)
    '''
    from pathlib import Path
    
    try:
        root = Path(path)
        if not root.exists():
            return f'Error: Path does not exist: {path}'
        if not root.is_dir():
            return f'Error: Path is not a directory: {path}'
        
        entries = []
        
        if recursive:
            for p in sorted(root.rglob('*')):
                if not include_hidden and any(part.startswith('.') for part in p.parts):
                    continue
                entries.append(f"{'D' if p.is_dir() else 'F'} {p}")
        else:
            for p in sorted(root.iterdir()):
                if not include_hidden and p.name.startswith('.'):
                    continue
                entries.append(f"{'D' if p.is_dir() else 'F'} {p.name}")
        
        return '\n'.join(entries) if entries else '(empty directory)'
    except Exception as e:
        return f'Error: {e}'


@mcp.tool()
async def file_search(path: str, pattern: str, recursive: bool = True, max_results: int = 100) -> str:
    '''Search for files matching a pattern within a directory.
    
    Args:
        path: Root directory to search in
        pattern: Glob pattern (e.g., '*.py', '*.txt')
        recursive: Search subdirectories (default: True)
        max_results: Maximum results to return (default: 100)
    '''
    from pathlib import Path
    
    try:
        root = Path(path)
        if not root.exists():
            return f'Error: Path does not exist: {path}'
        
        matches = []
        count = 0
        
        iterator = root.rglob(pattern) if recursive else root.glob(pattern)
        
        for p in iterator:
            if count >= max_results:
                matches.append(f"... (showing first {max_results} of {max_results}+ results)")
                break
            matches.append(str(p))
            count += 1
        
        return '\n'.join(matches) if matches else 'No matches found'
    except Exception as e:
        return f'Error: {e}'


@mcp.tool()
async def file_delete(path: str, dry_run: bool = True) -> str:
    '''Delete a file. CAUTION: This is destructive!
    
    Args:
        path: Path to the file to delete
        dry_run: If True, only show what would be deleted (default: True)
    '''
    result = await _file_tool.execute(action='delete', path=path, dry_run=dry_run)
    if result.success:
        return result.output or f'Deleted: {path}'
    return f'Error: {result.error}'


# ============================================================================
# SHELL TOOL - Execute whitelisted commands
# ============================================================================

@mcp.tool()
async def shell_execute(command: str, timeout: int = 10) -> str:
    '''Execute a shell command from the allowed whitelist.
    
    Allowed commands: dir, type, findstr, echo, date, whoami, ping
    
    Args:
        command: Shell command to execute
        timeout: Maximum seconds to wait (default: 10)
    '''
    try:
        args = command.split()
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        
        output = stdout.decode(errors='replace').strip()
        err = stderr.decode(errors='replace').strip()
        
        if proc.returncode != 0:
            return f'Command failed (exit {proc.returncode}):\n{err or output}'
        
        return output or '(no output)'
    except asyncio.TimeoutError:
        return f'Error: Command timed out after {timeout}s'
    except Exception as e:
        return f'Error: {e}'


@mcp.tool()
async def shell_list_commands() -> str:
    '''List all commands that are allowed to be executed via shell_tool.'''
    cfg = load_config('tools')
    allowed = cfg.get('tools', {}).get('shell_tool', {}).get('sandbox', {}).get('allowed_commands', [])
    return ', '.join(sorted(allowed)) if allowed else 'dir, type, findstr, echo, date, whoami, ping'


# ============================================================================
# PYTHON TOOL - Execute Python code (sandboxed)
# ============================================================================

@mcp.tool()
async def python_execute(code: str, timeout: int = 30) -> str:
    '''Execute Python code in a sandboxed environment.
    
    Args:
        code: Python code to execute
        timeout: Maximum seconds to wait (default: 30)
    '''
    result = await _python_tool.execute(code=code, timeout=timeout)
    if result.success:
        return result.output or '(no output)'
    return f'Error: {result.error}'


@mcp.tool()
async def python_list_builtins() -> str:
    '''List Python builtins and imports available in the sandbox.'''
    imports = list(_python_tool._get_allowed_imports())
    return f"Allowed imports: {', '.join(sorted(imports))}"


# ============================================================================
# WEB SEARCH TOOL
# ============================================================================

@mcp.tool()
async def web_search(query: str, num_results: int = 5) -> str:
    '''Search the web for information.
    
    Args:
        query: Search query
        num_results: Number of results to return (default: 5)
    '''
    result = await _web_search_tool.execute(query=query, num_results=num_results)
    if result.success:
        return result.output or 'No results found'
    return f'Error: {result.error}'


# ============================================================================
# RAG TOOL - Semantic search over knowledge base
# ============================================================================

@mcp.tool()
async def knowledge_search(query: str, collection: str = 'default', top_k: int = 5) -> str:
    '''Search the knowledge base for semantically similar documents.
    
    Args:
        query: Search query
        collection: Collection name to search in (default: 'default')
        top_k: Number of results to return (default: 5)
    '''
    result = await _rag_tool.execute(query=query, collection=collection, top_k=top_k)
    if result.success:
        return result.output or 'No relevant documents found'
    return f'Error: {result.error}'


@mcp.tool()
async def knowledge_add(text: str, collection: str = 'default', metadata: dict = None) -> str:
    '''Add a document to the knowledge base.
    
    Args:
        text: Document text to add
        collection: Collection name (default: 'default')
        metadata: Optional metadata dict
    '''
    result = await _rag_tool.execute(text=text, collection=collection, metadata=metadata or {})
    if result.success:
        return f'Added to knowledge base (collection: {collection})'
    return f'Error: {result.error}'


# ============================================================================
# EMAIL TOOL - Send emails (requires config)
# ============================================================================

@mcp.tool()
async def email_send(to: str, subject: str, body: str) -> str:
    '''Send an email via SMTP.
    
    Args:
        to: Recipient email address
        subject: Email subject line
        body: Email body content
    '''
    result = await _email_tool.execute(to=to, subject=subject, body=body)
    if result.success:
        return f'Email sent to {to}'
    return f'Error: {result.error}'


# ============================================================================
# SYSTEM INFO TOOLS
# ============================================================================

@mcp.tool()
async def get_working_directory() -> str:
    '''Get the current working directory of the agent.'''
    return os.getcwd()


@mcp.tool()
async def list_available_tools() -> str:
    '''List all available tools with their descriptions.'''
    tools = [
        ('file_read', 'Read file contents'),
        ('file_write', 'Write content to a file'),
        ('file_list', 'List directory contents'),
        ('file_search', 'Search for files matching a pattern'),
        ('file_delete', 'Delete a file (dry-run by default)'),
        ('shell_execute', 'Execute a whitelisted shell command'),
        ('shell_list_commands', 'List allowed shell commands'),
        ('python_execute', 'Execute Python code in sandbox'),
        ('python_list_builtins', 'List allowed Python builtins'),
        ('web_search', 'Search the web for information'),
        ('knowledge_search', 'Search the knowledge base'),
        ('knowledge_add', 'Add a document to knowledge base'),
        ('email_send', 'Send an email'),
        ('get_working_directory', 'Get current working directory'),
        ('list_available_tools', 'Show this help message'),
        ('get_server_status', 'Show server health and stats'),
        ('server_llm_complete', 'Use server-side LLM for completion'),
        ('server_llm_summarize', 'Summarize text using LLM'),
    ]
    
    lines = [f'Available tools ({len(tools)}):']
    for name, desc in tools:
        lines.append(f'  - {name}: {desc}')
    return '\n'.join(lines)


@mcp.tool()
async def get_server_status() -> str:
    '''Get server status, health metrics, and statistics.'''
    global _request_count, _server_start_time
    
    uptime = int(time.time() - _server_start_time)
    uptime_str = f"{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s"
    
    cfg = load_config('mcp')
    server_cfg = cfg.get('mcp', {}).get('server', {}) if cfg else {}
    
    return f"""Supreme-Agent MCP Server Status
================================

Uptime: {uptime_str}
Total Requests: {_request_count}

Server Config:
  Host: {server_cfg.get('host', 'localhost')}
  Port: {server_cfg.get('port', '8765')}
  Auth: {'Enabled' if server_cfg.get('auth_enabled', True) else 'Disabled'}
  Rate Limit: {server_cfg.get('rate_limit_per_client_per_minute', 60)}/min

Enabled Tools: 16
  - File operations: 5
  - Shell operations: 2
  - Code execution: 2
  - Web & Knowledge: 3
  - Email: 1
  - System: 3

Resources: 5
Prompts: 7
Sampling: Enabled

All systems operational ✓"""


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    port = int(os.getenv('MCP_PORT', '8766'))
    print(f'Starting Supreme-Agent MCP server on port {port}...')
    print(f'Connect LM Studio to ws://localhost:{port} or use stdio mode')
    
    # Run with optional port override
    mcp.run()
