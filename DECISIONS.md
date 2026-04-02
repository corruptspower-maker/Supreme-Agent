# Architectural Decision Records — Executive Agent

This document captures key architectural decisions made during initial project construction.

---

## ADR-001 — Async SQLite via `aiosqlite`

**Decision:** Use `aiosqlite` for all SQLite access (episodic, procedural, and audit stores).

**Rationale:** The agent runs an `asyncio` event loop at its core. Blocking SQLite calls with the standard `sqlite3` module would stall the loop during disk I/O. `aiosqlite` wraps the synchronous driver in a thread-pool executor transparently, keeping the event loop free.

---

## ADR-002 — 4 chars/token heuristic for token estimation

**Decision:** Token counting uses `len(text) // 4` instead of `tiktoken` or similar.

**Rationale:** Avoids a hard dependency on the OpenAI Python SDK / `tiktoken`. The heuristic is accurate enough (±10–15 %) for budget guard-railing and avoids adding 50 MB+ to the install footprint. Callers that need exact counts can swap in `tiktoken` at a higher layer.

---

## ADR-003 — YAML config merged at startup; env overrides via `EA_` prefix

**Decision:** All YAML files under `config/` are merged at startup by `get_full_config()`. Runtime overrides use `EA_SECTION__KEY=value` environment variables.

**Rationale:** Single-file configs become unwieldy; splitting by domain (agent, models, tools, …) improves readability. The `EA_` prefix convention prevents namespace collisions with other tools. Only two-level paths (`section.key`) are auto-resolved to keep the loader simple.

---

## ADR-004 — Screenshots stored in `data/screenshots/`

**Decision:** Screenshot files are written to `data/screenshots/<timestamp>.png`, created on first use.

**Rationale:** Centralising ephemeral runtime artefacts under `data/` keeps the source tree clean. The directory is created lazily so no empty folder needs to ship in the repository.

---

## ADR-005 — ChromaDB optional; graceful degradation

**Decision:** If ChromaDB is unavailable (import error or connection failure), `semantic_memory_enabled` is set to `false` and the agent continues without semantic search.

**Rationale:** ChromaDB has a large dependency tree and may not be available in all deployment environments. All semantic-search call-sites must check `semantic_memory_enabled` before querying; episodic and procedural memory remain fully operational.

---

## ADR-006 — Port availability checked before binding

**Decision:** Before starting the MCP server or web UI, the chosen port is probed with `socket.connect_ex()`.

**Rationale:** Binding to an already-occupied port raises a cryptic `OSError`; an explicit pre-flight check produces a human-readable error message and allows the agent to suggest an alternative port or exit cleanly.

---

## ADR-007 — Background tasks use `asyncio.create_task()`

**Decision:** All background work (heartbeat, compaction, checkpoint) is scheduled with `asyncio.create_task()`.

**Rationale:** Using `threading.Thread` or `concurrent.futures` would require explicit synchronisation primitives and risk race conditions on shared agent state. Native asyncio tasks cooperatively interleave with the main loop without OS-level thread overhead.

---

## ADR-008 — Self-improvement disabled by default

**Decision:** `enable_self_improvement: false` in `config/agent.yaml`; activates only after 24 h of runtime **and** 50 completed tasks.

**Rationale:** Self-modification is high-risk. The dual gate (time + volume) ensures the agent has accumulated enough real-world signal before attempting to rewrite its own tools or prompts. The feature can be enabled explicitly by setting `enable_self_improvement: true` in the YAML.

---

## ADR-009 — Tool hot-reload not supported

**Decision:** Newly generated or modified tools require an agent restart to take effect.

**Rationale:** Dynamic `importlib.reload()` of tool modules risks leaving stale references in the tool registry, partially-initialised objects, or shadowed names. A clean restart is safer and easier to reason about. The agent logs a clear message when a new tool is written to disk.
