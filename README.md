# Supreme-Agent (Executive Agent)

> A locally-hosted autonomous AI agent with planning, memory, safety enforcement, escalation, and a FastAPI web dashboard — powered by your own LM Studio instance.

---

## What It Is

Supreme-Agent is a personal **executive agent**: an async Python runtime that receives natural-language task requests, reasons over them with a local LLM, plans steps, routes work through typed tools, and stores results in a persistent multi-tier memory system. When the local model can't handle a task, it escalates — optionally reaching out to GitHub Copilot (GPT-4o) or Claude — before any human needs to be interrupted.

### Architecture at a glance

```
User (CLI / Web UI / MCP)
        │
        ▼
  ExecutiveAgent          ← orchestrator; owns the event loop
  ├── Reasoner            ← calls LM Studio for plan generation
  ├── Planner             ← turns LLM output into structured Plan objects
  ├── SafetyManager       ← vetoes plans; enforces rate limits & forbidden actions
  ├── Executor            ← dispatches steps through ToolRouter
  │   └── ToolRouter      ← resolves step → tool (file, shell, web, email, RAG, …)
  ├── MemoryManager       ← episodic + procedural (aiosqlite) + semantic (ChromaDB)
  ├── EscalationManager   ← circuit-breakers; tier-1/2/3 escalation chain
  ├── MCPServer           ← WebSocket server (port 8765)
  └── Web UI              ← FastAPI + Jinja2 dashboard (port 8000)
```

### Escalation chain

| Tier | Backend | Trigger |
|------|---------|---------|
| Local | LM Studio (`huihui-qwen3.5-9b-…`) | default |
| Tier 1 | GitHub Copilot API — GPT-4o | circuit breaker open or explicit escalation |
| Tier 2 | Claude (CLI, `--print` mode) | Tier 1 timeout / failure |
| Tier 3 | Claude in VS Code / Cline | Tier 2 timeout (human-in-the-loop fallback) |

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | |
| [LM Studio](https://lmstudio.ai) | Must be running on `http://localhost:1234/v1` with a model loaded |
| ChromaDB (optional) | Enables semantic memory; degrades gracefully if absent |
| GitHub OAuth app (optional) | Required only for Tier-1 Copilot escalation |

---

## Quick Start

```bash
# 1. Clone & install
git clone https://github.com/corruptspower-maker/Supreme-Agent.git
cd Supreme-Agent
pip install -e .

# 2. Configure
cp .env.example .env
# Edit .env — set LMSTUDIO_ENDPOINT if not on localhost:1234

# 3. Start LM Studio and load a model, then:

# Option A — one-shot task
python -m src.interface.cli run -t "Summarise the files in ./data and save a report to data/report.md"

# Option B — persistent agent with dashboard
python -m src.interface.cli serve
# → Dashboard: http://localhost:8000
# → MCP WebSocket: ws://localhost:8765

# 4. Health check
python -m src.interface.cli health
```

---

## Configuration

All config lives in `config/`. Every key can be overridden at runtime with an environment variable using the `EA_SECTION__KEY` convention:

```bash
EA_AGENT__MAX_CONCURRENT_TASKS=5
EA_SAFETY__SAFETY_MODE_DEFAULT=monitored
```

### Key files

| File | Controls |
|---|---|
| `config/agent.yaml` | concurrency, checkpointing, self-improvement gate |
| `config/models.yaml` | local model endpoint; escalation tier endpoints/models |
| `config/safety.yaml` | rate limits, forbidden actions, sandbox allowlists |
| `config/memory.yaml` | retention windows, compaction schedules |
| `config/escalation.yaml` | circuit-breaker thresholds |
| `config/tools.yaml` | tool enable/disable flags |
| `config/ui.yaml` | web UI host/port |
| `config/mcp.yaml` | MCP server host/port |

---

## Built-in Tools

| Tool | What it does |
|---|---|
| `file_tool` | Read, write, list files within the working directory |
| `shell_tool` | Run allowlisted shell commands (sandboxed; timeout enforced) |
| `python_tool` | Execute Python snippets in a restricted import sandbox |
| `web_search_tool` | Fetch and parse web content |
| `rag_tool` | Retrieve chunks from the semantic memory store |
| `email_tool` | Send email (rate-limited; requires SMTP config) |

New tools are picked up after an agent restart (`tool hot-reload is intentionally not supported` — see ADR-009).

---

## Safety

Safety modes from least to most restrictive: `monitored → full → strict → severe_locked`.  
`SEVERE_LOCKED` cannot be unlocked programmatically — restart required.

Actions that always require human confirmation (configurable in `safety.yaml`):
- `email_send`, `file_delete`, `shell_execute`, `browser_navigate_new_domain`

Hardcoded forbidden actions (cannot be overridden by config):
- `system_file_modification`, `registry_edit`, `credential_storage_access`, `full_disk_delete`, `kernel_modification`

---

## Self-Improvement

Disabled by default. Activates only when **both** conditions are met:
1. Agent has been running for ≥ 24 hours
2. ≥ 50 tasks have been completed

Enable explicitly: set `enable_self_improvement: true` in `config/agent.yaml`.

---

## Development

```bash
# Run all tests (231 tests, ~13 s)
pytest tests/ -v

# Lint
ruff check src/ tests/

# Or via Makefile
make test
make lint
```

---

## Project Structure

```
src/
  core/          # Executive orchestrator, Reasoner, Planner, Executor, ToolRouter
  memory/        # MemoryManager (aiosqlite episodic/procedural + ChromaDB semantic)
  safety/        # SafetyManager — plan vetting, rate limiting, audit log
  escalation/    # EscalationManager — circuit breakers, tier routing
  tools/         # Tool registry + individual tool implementations
  interface/     # CLI (Click + Rich) and Web UI (FastAPI + Jinja2)
  mcp_servers/   # WebSocket MCP server + auth
  utils/         # Config loader, LM Studio client, logging, token counter, screenshot
config/          # YAML configuration files (one per domain)
data/            # Runtime artefacts: checkpoint.json, audit.db, screenshots/
tests/           # 231 pytest tests covering every subsystem
```

---

## Architectural Decisions

See [DECISIONS.md](DECISIONS.md) for the full ADR log (ADR-001 through ADR-009), covering async SQLite, token heuristics, config layering, screenshot storage, ChromaDB optional dependency, port pre-flight checks, asyncio task scheduling, self-improvement gating, and tool hot-reload policy.

---

## License

MIT
