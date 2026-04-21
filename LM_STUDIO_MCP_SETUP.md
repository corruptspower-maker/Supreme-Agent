# LM Studio MCP Setup Guide

This guide explains how to connect **LM Studio** to **Supreme-Agent's MCP server** to enable tool-augmented inference with a full-featured MCP implementation.

## What's New in v2.0

The MCP server now includes the full MCP protocol implementation:

| Feature | Description |
|---------|-------------|
| **Tools** | 18 tools for file, shell, code, web, and knowledge operations |
| **Resources** | 6 URI-based resources for config, tools, and server info |
| **Prompts** | 7 reusable prompt templates for common tasks |
| **Sampling** | Server-side LLM calls via LM Studio API |

## Setup Instructions

### Step 1: Install Dependencies

```bash
cd c:/Users/Power/Repos/Supreme-Agent
uv sync
```

### Step 2: Configure LM Studio

1. Open **LM Studio**
2. Go to **Developer** tab (left sidebar)
3. Make sure **Enable Local Server** is ON
4. Set your **API Key** (or disable auth if preferred)
5. Note the **port** (default: 1234)

### Step 3: Add API Key to .env

```env
LM_STUDIO_API_KEY=your-api-key-here
LM_STUDIO_BASE_URL=http://localhost:1234/v1
```

### Step 4: Connect in LM Studio

In LM Studio's Developer → MCP section:

1. Click **Add Server**
2. Select protocol: **Stdio** (recommended)
3. Configure:
   ```
   Command: uv
   Args: run src/mcp_servers/lmstudio_exposer.py
   Working Directory: C:/Users/Power/Repos/Supreme-Agent
   ```

### Step 5: Verify Connection

You should see **18 tools** and **6 resources** available after connecting.

---

## Available Tools

### File Operations (5)

| Tool | Description | Risk |
|------|-------------|------|
| `file_read` | Read file contents with line range support | Safe |
| `file_write` | Write content to files (auto-creates dirs) | Medium |
| `file_list` | List directory contents with filters | Safe |
| `file_search` | Search for files by glob pattern | Safe |
| `file_delete` | Delete files (dry-run default) | High |

### Shell Operations (2)

| Tool | Description | Risk |
|------|-------------|------|
| `shell_execute` | Execute whitelisted commands | Medium |
| `shell_list_commands` | List allowed commands | Safe |

### Code Execution (2)

| Tool | Description | Risk |
|------|-------------|------|
| `python_execute` | Execute Python in sandbox | Medium |
| `python_list_builtins` | List allowed imports | Safe |

### Web & Knowledge (3)

| Tool | Description | Risk |
|------|-------------|------|
| `web_search` | Search the web | Safe |
| `knowledge_search` | Semantic search in knowledge base | Safe |
| `knowledge_add` | Add documents to knowledge base | Safe |

### System (6)

| Tool | Description | Risk |
|------|-------------|------|
| `email_send` | Send emails via SMTP | High |
| `get_working_directory` | Get current directory | Safe |
| `list_available_tools` | List all tools | Safe |
| `get_server_status` | Server health and stats | Safe |
| `server_llm_complete` | Server-side LLM completion | Safe |
| `server_llm_summarize` | Summarize text via LLM | Safe |

---

## MCP Resources

Access server information via URIs:

| URI | Description |
|-----|-------------|
| `file://readme` | README content |
| `file://config` | Server configuration |
| `file://tools` | All tool schemas |
| `file://allowed-shells` | Whitelisted shell commands |
| `file://sandbox-allowed-imports` | Allowed Python imports |
| `server://info` | Server capabilities |

---

## MCP Prompts

Pre-built prompt templates for common tasks:

| Prompt | Use Case |
|--------|----------|
| `analyze_codebase` | Analyze project structure |
| `debug_error` | Debug error messages |
| `review_code` | Code review |
| `search_and_replace` | Find and replace patterns |
| `write_tests` | Generate test files |
| `research_topic` | Research information |
| `refactor_code` | Refactor code |

---

## Architecture

```
┌─────────────────┐     MCP (stdio)      ┌─────────────────────────┐
│   LM Studio     │◄────────────────────►│  Supreme-Agent MCP      │
│   (Model)       │                      │  (lmstudio_exposer.py) │
└─────────────────┘                      └───────────┬─────────────┘
                                                      │
                                    ┌─────────────────┼─────────────────┐
                                    │                 │                 │
                              ┌─────▼─────┐    ┌──────▼──────┐   ┌─────▼─────┐
                              │ File Tool │    │ Shell Tool  │   │  RAG Tool │
                              └───────────┘    └─────────────┘   └───────────┘
                                    │                 │                 │
                              ┌─────▼─────┐    ┌──────▼──────┐   ┌─────▼─────┐
                              │  Python   │    │ Web Search  │   │   Email   │
                              └───────────┘    └─────────────┘   └───────────┘
```

---

## Troubleshooting

### Tools not appearing
1. Check the server started without errors
2. Verify the working directory is correct
3. Try restarting LM Studio

### Connection refused
Make sure the port isn't blocked by firewall and isn't in use.

### LLM calls failing
Verify `LM_STUDIO_API_KEY` and `LM_STUDIO_BASE_URL` in `.env`

---

## Security Notes

- **Shell commands** are whitelisted: `dir, type, findstr, echo, date, whoami, ping`
- **Python execution** is sandboxed with limited imports
- **Email sending** requires SMTP credentials in environment
- **File delete** defaults to dry-run mode for safety

## Standalone Server

You can also run the server standalone:

```bash
cd c:/Users/Power/Repos/Supreme-Agent
uv run src/mcp_servers/lmstudio_exposer.py
```

This starts the MCP server using stdio transport, ready for LM Studio to connect.