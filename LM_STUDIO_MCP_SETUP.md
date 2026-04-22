# LM Studio MCP Setup Guide

This guide explains how to connect **LM Studio** to **Supreme-Agent's MCP harness** so the model uses a single tool entrypoint: `run_agent`.

## Harness Mode (Single Tool)

In harness mode, LM Studio sees only one MCP tool:

- `run_agent(goal: string)` → sends your request into Supreme-Agent's full orchestration loop (planning, safety checks, execution, retries, verification).

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

You should see exactly **1 tool**:

- `run_agent`

---

## How it Works

LM Studio model (9B) → MCP `run_agent` → Supreme-Agent internals:

- Reasoner + Planner
- SafetyManager
- Executor + ToolRouter
- Internal tools (filesystem/search/etc.) used by the agent, not directly by LM Studio
- Memory + audit trail

---

## Architecture

```
┌─────────────────┐     MCP (stdio)      ┌─────────────────────────┐
│   LM Studio     │◄────────────────────►│ run_agent MCP tool      │
│   (Model)       │                      │ (lmstudio_exposer.py)   │
└─────────────────┘                      └───────────┬─────────────┘
                                                     │
                                                     ▼
                                           ┌───────────────────┐
                                           │ ExecutiveAgent    │
                                           │ (full internals)  │
                                           └───────────────────┘
```

---

## Troubleshooting

### `run_agent` not appearing
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
