"""FastAPI web UI — status dashboard, task submission, and WebSocket live updates."""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from loguru import logger
from pydantic import BaseModel

# ─── Pydantic request/response models ────────────────────────────────────────


class SubmitTaskRequest(BaseModel):
    text: str
    source: str = "web_ui"


class SubmitTaskResponse(BaseModel):
    task_id: str
    status: str


# ─── HTML dashboard (single-file, no external deps) ──────────────────────────

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Supreme Agent Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #e6edf3; }
  header { background: #161b22; border-bottom: 1px solid #30363d; padding: 16px 24px;
           display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 1.25rem; font-weight: 600; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem;
           font-weight: 600; text-transform: uppercase; }
  .badge-green { background: #1a7f37; color: #56d364; }
  .badge-red   { background: #6e1616; color: #f85149; }
  .badge-yellow { background: #7d4e00; color: #e3b341; }
  main { max-width: 1100px; margin: 0 auto; padding: 24px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; }
  .card h2 { font-size: 0.875rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.05em;
             margin-bottom: 12px; }
  .stat { font-size: 2rem; font-weight: 700; color: #58a6ff; }
  .stat-label { font-size: 0.8rem; color: #8b949e; margin-top: 4px; }
  .form-row { display: flex; gap: 8px; }
  textarea { flex: 1; background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
             color: #e6edf3; padding: 10px 12px; font-size: 0.9rem; resize: vertical;
             min-height: 60px; font-family: inherit; }
  textarea:focus { outline: none; border-color: #58a6ff; }
  button { background: #238636; color: #fff; border: none; border-radius: 6px; padding: 10px 18px;
           font-size: 0.9rem; font-weight: 600; cursor: pointer; white-space: nowrap; }
  button:hover { background: #2ea043; }
  button:disabled { background: #21262d; color: #8b949e; cursor: not-allowed; }
  .log { background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
         height: 280px; overflow-y: auto; padding: 12px; font-family: monospace; font-size: 0.8rem; }
  .log-entry { padding: 3px 0; border-bottom: 1px solid #161b22; }
  .log-entry:last-child { border-bottom: none; }
  .log-ts { color: #6e7681; margin-right: 8px; }
  .full { grid-column: 1 / -1; }
  .status-row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
  .kv { display: flex; gap: 6px; align-items: center; font-size: 0.85rem; }
  .kv-key { color: #8b949e; }
  .kv-val { color: #e6edf3; font-weight: 600; }
  .cb-grid { display: flex; gap: 8px; flex-wrap: wrap; }
  .cb { padding: 3px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
  .cb-closed { background: #1a7f37; color: #56d364; }
  .cb-open   { background: #6e1616; color: #f85149; }
  #conn-status { margin-left: auto; }
</style>
</head>
<body>
<header>
  <h1>⚡ Supreme Agent</h1>
  <span id="agent-badge" class="badge badge-red">offline</span>
  <span id="conn-status" class="badge badge-yellow">connecting…</span>
</header>
<main>
  <div class="grid">
    <div class="card">
      <h2>Status</h2>
      <div class="status-row">
        <div class="kv"><span class="kv-key">mode:</span><span class="kv-val" id="safety-mode">—</span></div>
        <div class="kv"><span class="kv-key">active:</span><span class="kv-val" id="active-tasks">—</span></div>
        <div class="kv"><span class="kv-key">queued:</span><span class="kv-val" id="queued-tasks">—</span></div>
        <div class="kv"><span class="kv-key">paused:</span><span class="kv-val" id="paused">—</span></div>
      </div>
      <h2 style="margin-top:14px">Circuit Breakers</h2>
      <div class="cb-grid" id="cb-grid">—</div>
    </div>
    <div class="card">
      <h2>Submit Task</h2>
      <div class="form-row">
        <textarea id="task-input" placeholder="Describe a task for the agent…"></textarea>
        <button id="submit-btn" onclick="submitTask()">Run</button>
      </div>
      <div id="submit-result" style="margin-top:10px; font-size:0.85rem; color:#8b949e;"></div>
    </div>
    <div class="card full">
      <h2>Reasoning Log</h2>
      <div class="log" id="reasoning-log"></div>
    </div>
  </div>
</main>
<script>
let ws = null;
let reconnectTimer = null;

function connect() {
  ws = new WebSocket("ws://" + location.host + "/ws");
  ws.onopen = () => {
    document.getElementById("conn-status").textContent = "live";
    document.getElementById("conn-status").className = "badge badge-green";
    clearTimeout(reconnectTimer);
  };
  ws.onmessage = (e) => {
    const d = JSON.parse(e.data);
    if (d.type === "status") updateStatus(d.data);
  };
  ws.onclose = () => {
    document.getElementById("conn-status").textContent = "reconnecting…";
    document.getElementById("conn-status").className = "badge badge-yellow";
    reconnectTimer = setTimeout(connect, 3000);
  };
  ws.onerror = () => ws.close();
}

function updateStatus(s) {
  const running = s.running;
  const badge = document.getElementById("agent-badge");
  badge.textContent = running ? (s.paused ? "paused" : "running") : "offline";
  badge.className = "badge " + (running ? (s.paused ? "badge-yellow" : "badge-green") : "badge-red");

  document.getElementById("safety-mode").textContent = s.safety_mode || "—";
  document.getElementById("active-tasks").textContent = s.active_tasks ?? "—";
  document.getElementById("queued-tasks").textContent = s.queued_tasks ?? "—";
  document.getElementById("paused").textContent = s.paused ? "yes" : "no";

  // Circuit breakers
  const cbGrid = document.getElementById("cb-grid");
  const cbs = s.circuit_breaker_states || {};
  cbGrid.innerHTML = Object.entries(cbs).map(([tier, open]) =>
    `<span class="cb ${open ? 'cb-open' : 'cb-closed'}">${tier}: ${open ? 'OPEN' : 'closed'}</span>`
  ).join("") || "—";

  // Reasoning log
  const log = document.getElementById("reasoning-log");
  const buf = s.reasoning_buffer || [];
  const now = new Date().toLocaleTimeString();
  buf.forEach(msg => {
    const el = document.createElement("div");
    el.className = "log-entry";
    el.innerHTML = `<span class="log-ts">${now}</span>${msg}`;
    log.appendChild(el);
  });
  // Auto-scroll
  log.scrollTop = log.scrollHeight;
}

async function submitTask() {
  const input = document.getElementById("task-input");
  const btn = document.getElementById("submit-btn");
  const result = document.getElementById("submit-result");
  const text = input.value.trim();
  if (!text) return;
  btn.disabled = true;
  result.textContent = "Submitting…";
  try {
    const resp = await fetch("/tasks", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text, source: "web_ui"}),
    });
    const data = await resp.json();
    if (resp.ok) {
      result.textContent = "✓ Task submitted: " + data.task_id;
      input.value = "";
    } else {
      result.textContent = "Error: " + (data.detail || "unknown");
    }
  } catch(e) {
    result.textContent = "Network error: " + e.message;
  } finally {
    btn.disabled = false;
  }
}

connect();
</script>
</body>
</html>"""


# ─── WebSocket connection manager ─────────────────────────────────────────────


class _ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections = [c for c in self._connections if c is not ws]

    async def broadcast(self, data: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


_manager = _ConnectionManager()


# ─── App factory ──────────────────────────────────────────────────────────────


def create_app(agent=None) -> FastAPI:
    """Create and return the FastAPI application, optionally bound to an agent."""
    app = FastAPI(title="Supreme Agent", version="0.1.0")
    app.state.agent = agent
    try:
        from src.api.agent import router as agent_router
        app.include_router(agent_router, prefix="/api")
    except ImportError as exc:
        # API router is optional in environments without full deps/initialization
        logger.warning(f"Optional API router could not be imported: {exc}")
    except Exception:
        logger.exception("Unexpected error while importing or including the API router")
        raise

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> HTMLResponse:
        return HTMLResponse(_DASHBOARD_HTML)

    @app.get("/status")
    async def get_status() -> dict:
        ag = app.state.agent
        if ag is None:
            return {"running": False, "error": "Agent not initialized"}
        return ag.get_status()

    @app.post("/tasks", response_model=SubmitTaskResponse)
    async def submit_task(req: SubmitTaskRequest) -> SubmitTaskResponse:
        ag = app.state.agent
        if ag is None:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        task = await ag.submit_request(req.text, source=req.source)
        return SubmitTaskResponse(task_id=task.id, status=task.status.value)

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await _manager.connect(ws)
        ag = app.state.agent
        try:
            while True:
                # Push status update every 2 seconds
                if ag is not None:
                    status = ag.get_status()
                    # Only send the latest reasoning messages on each tick
                    status["reasoning_buffer"] = list(ag._reasoning_buffer)[-5:]
                    await ws.send_text(json.dumps({"type": "status", "data": status}))
                await asyncio.sleep(2)
        except WebSocketDisconnect:
            _manager.disconnect(ws)
        except Exception:
            _manager.disconnect(ws)

    return app


async def start_web_ui(agent, host: str = "localhost", port: int = 8000) -> None:
    """Start the uvicorn web server in the background."""
    import uvicorn

    app = create_app(agent)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    logger.info(f"Web UI starting at http://{host}:{port}")
    await server.serve()
