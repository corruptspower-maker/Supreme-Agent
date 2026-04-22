"""Executive Agent — main orchestrator for the agent system."""

from __future__ import annotations

import asyncio
import json
import socket
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from src.core.models import (
    SafetyMode,
    Task,
    TaskStatus,
    UserRequest,
)
from src.utils.config import get_full_config
from src.utils.logging import setup_logging

CHECKPOINT_PATH = Path("data/checkpoint.json")


def _check_port(host: str, port: int) -> bool:
    """Return True if the port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


class ExecutiveAgent:
    """Main orchestrator for the Executive Agent."""

    def __init__(self) -> None:
        cfg = get_full_config()
        agent_cfg = cfg.get("agent", {})
        self._max_concurrent: int = agent_cfg.get("max_concurrent_tasks", 3)
        self._checkpoint_interval: int = agent_cfg.get("checkpoint_interval_seconds", 30)
        self._heartbeat_interval: int = agent_cfg.get("heartbeat_interval_seconds", 10)
        self._queue_warn_size: int = agent_cfg.get("task_queue_warn_size", 10)
        ports = agent_cfg.get("ports", {})
        self._mcp_port: int = ports.get("mcp_server", 8765)
        self._ui_port: int = ports.get("web_ui", 8000)

        self._active_tasks: dict[str, Task] = {}
        self._task_queue: deque[UserRequest] = deque()
        self._safety_mode: SafetyMode = SafetyMode.FULL
        self._running: bool = False
        self._paused: bool = False

        self.reasoner = None
        self.planner = None
        self.executor = None
        self.memory = None
        self.safety = None
        self.escalation = None

        self._reasoning_buffer: deque[str] = deque(maxlen=100)

    def check_ports(self) -> None:
        """Check port availability before starting. Exit if conflicts found."""
        for port in (self._mcp_port, self._ui_port):
            if _check_port("localhost", port):
                logger.error(f"Port {port} is already in use. Cannot start agent.")
                raise SystemExit(1)

    async def start(self) -> None:
        """Start the agent and all subsystems."""
        setup_logging()
        self.check_ports()

        self._running = True
        logger.info("Executive Agent starting...")

        await self._load_checkpoint()
        await self._init_subsystems()

        asyncio.create_task(self._heartbeat_loop())
        asyncio.create_task(self._checkpoint_loop())

        logger.info("Executive Agent ready.")

    async def _init_subsystems(self) -> None:
        """Initialize and wire all subsystems."""
        from src.core.executor import Executor
        from src.core.planner import Planner
        from src.core.reasoner import Reasoner
        from src.core.tool_router import ToolRouter
        from src.escalation.manager import EscalationManager
        from src.mcp_servers.server import MCPServer
        from src.memory.manager import MemoryManager
        from src.safety.manager import SafetyManager
        from src.tools.registry import ToolRegistry
        from src.utils.lm_studio_client import LMStudioClient

        # Memory
        self.memory = MemoryManager()
        await self.memory.start()
        asyncio.create_task(self.memory.compaction_loop())

        # Safety
        self.safety = SafetyManager()
        await self.safety.start()

        # Tools
        registry = ToolRegistry()
        registry.autodiscover()
        run_agent_tool = registry.get("run_agent")
        if run_agent_tool and hasattr(run_agent_tool, "_agent"):
            run_agent_tool._agent = self
        self._registry = registry

        # LM Studio client (shared; must be closed on shutdown)
        self._lm_client = LMStudioClient()
        await self._lm_client.__aenter__()

        # Core pipeline
        self.planner = Planner()
        self.reasoner = Reasoner(self._lm_client)

        # Escalation
        self.escalation = EscalationManager()

        router = ToolRouter(registry)
        self.executor = Executor(
            router=router,
            escalation_manager=self.escalation,
            safety_manager=self.safety,
        )

        # MCP server
        cfg = get_full_config()
        mcp_cfg = cfg.get("mcp", {}).get("server", {})
        mcp_host = mcp_cfg.get("host", "localhost")
        mcp_port = mcp_cfg.get("port", self._mcp_port)
        self._mcp_server = MCPServer(host=mcp_host, port=mcp_port, agent=self)
        await self._mcp_server.start()

        # Web UI
        ui_cfg = cfg.get("ui", {})
        ui_host = ui_cfg.get("host", "localhost")
        ui_port = ui_cfg.get("port", self._ui_port)
        from src.interface.web import start_web_ui
        asyncio.create_task(start_web_ui(self, host=ui_host, port=ui_port))

        logger.info("All subsystems initialized")

    async def submit_request(self, text: str, source: str = "cli") -> Task:
        """Submit a user request for processing."""
        request = UserRequest(text=text, source=source)
        task = Task(request=request)

        if len(self._active_tasks) >= self._max_concurrent:
            self._task_queue.append(request)
            queue_size = len(self._task_queue)
            msg = f"Task queued, currently running {len(self._active_tasks)} tasks."
            logger.info(msg)
            self._reasoning_buffer.append(msg)
            if queue_size > self._queue_warn_size:
                warn = f"Warning: task queue has {queue_size} items."
                logger.warning(warn)
                self._reasoning_buffer.append(warn)
            return task

        self._active_tasks[task.id] = task
        asyncio.create_task(self._process_task(task))
        return task

    async def run_async(self, goal: str, source: str = "api") -> dict:
        """Run a goal and wait for completion, returning a compact result."""
        task = await self.submit_request(goal, source=source)
        while task.status in {TaskStatus.PENDING, TaskStatus.PLANNING, TaskStatus.EXECUTING}:
            await asyncio.sleep(0.1)
        return {
            "task_id": task.id,
            "status": task.status.value,
            "error": task.error,
            "results": [r.model_dump(mode="json") for r in task.results],
        }

    async def _process_task(self, task: Task) -> None:
        """Process a single task through plan → execute → memory → report."""
        task.started_at = datetime.now(tz=timezone.utc)
        task.status = TaskStatus.PLANNING
        self._reasoning_buffer.append(f"Planning: {task.request.text}")

        try:
            memory_context = ""
            if self.memory:
                memory_context = await self.memory.search(task.request.text)

            if self.reasoner:
                task.plan = await self.reasoner.plan(task.request, memory_context=memory_context)

            if self.safety and task.plan:
                approved, reason = await self.safety.check_plan(task.plan, self._safety_mode)
                if not approved:
                    task.status = TaskStatus.FAILED
                    task.error = f"Safety check failed: {reason}"
                    self._reasoning_buffer.append(f"Safety blocked: {reason}")
                    return

            if self.executor and task.plan:
                task = await self.executor.execute_plan(
                    task, registry=getattr(self, "_registry", None)
                )
            else:
                task.status = TaskStatus.COMPLETED

            if self.memory:
                await self.memory.store_task_result(task)
                await self._store_step_strategies(task)

        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}")
            task.status = TaskStatus.FAILED
            task.error = str(e)
        finally:
            self._active_tasks.pop(task.id, None)
            self._reasoning_buffer.append(f"Task {task.status.value}: {task.request.text}")
            if self._task_queue and not self._paused:
                next_req = self._task_queue.popleft()
                next_task = Task(request=next_req)
                self._active_tasks[next_task.id] = next_task
                asyncio.create_task(self._process_task(next_task))

    def pause(self) -> None:
        """Pause after current steps complete."""
        self._paused = True
        self._reasoning_buffer.append("Paused after current step completes")
        logger.info("Agent paused")

    def resume(self) -> None:
        """Resume processing queued tasks."""
        self._paused = False
        logger.info("Agent resumed")
        if self._task_queue:
            next_req = self._task_queue.popleft()
            next_task = Task(request=next_req)
            self._active_tasks[next_task.id] = next_task
            asyncio.create_task(self._process_task(next_task))

    def set_safety_mode(self, mode: SafetyMode) -> None:
        """Update the active safety mode."""
        if mode == SafetyMode.SEVERE_LOCKED:
            logger.warning("Cannot unlock SEVERE safety mode")
            return
        self._safety_mode = mode
        logger.info(f"Safety mode set to: {mode}")

    async def _heartbeat_loop(self) -> None:
        """Periodic heartbeat to confirm agent is alive."""
        while self._running:
            logger.debug("Heartbeat ♥")
            await asyncio.sleep(self._heartbeat_interval)

    async def _checkpoint_loop(self) -> None:
        """Periodically save state checkpoint."""
        while self._running:
            await asyncio.sleep(self._checkpoint_interval)
            await self._save_checkpoint()

    async def _save_checkpoint(self) -> None:
        """Save current state to checkpoint.json."""
        try:
            CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "active_tasks": [t.model_dump(mode="json") for t in self._active_tasks.values()],
                "task_queue": [r.model_dump(mode="json") for r in self._task_queue],
                "safety_mode": self._safety_mode.value,
                "circuit_breaker_states": {},
                "memory_session": list(self._reasoning_buffer),
                "saved_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            CHECKPOINT_PATH.write_text(json.dumps(data, indent=2))
            logger.debug("Checkpoint saved")
        except Exception as e:
            logger.error(f"Checkpoint save failed: {e}")

    async def _load_checkpoint(self) -> None:
        """Load state from checkpoint.json if it exists."""
        if not CHECKPOINT_PATH.exists():
            return
        try:
            data = json.loads(CHECKPOINT_PATH.read_text())
            mode_str = data.get("safety_mode", "full")
            self._safety_mode = SafetyMode(mode_str)
            logger.info("Checkpoint loaded")
        except Exception as e:
            logger.warning(f"Checkpoint load failed: {e}")

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        self._running = False
        logger.info("Shutting down — waiting for active tasks (30s max)...")

        for _ in range(30):
            if not self._active_tasks:
                break
            await asyncio.sleep(1)

        await self._save_checkpoint()

        if hasattr(self, "_mcp_server") and self._mcp_server:
            await self._mcp_server.stop()

        if hasattr(self, "_lm_client") and self._lm_client:
            await self._lm_client.__aexit__(None, None, None)

        logger.info("Agent shutdown complete")

    async def _store_step_strategies(self, task: Task) -> None:
        """Store failed/successful step strategies in memory for future planning."""
        if not self.memory or not task.plan:
            return
        for step in task.plan.steps:
            from src.core.models import MemoryEntry, StepStatus
            if step.status == StepStatus.FAILED and step.failed_strategies:
                for strategy in step.failed_strategies:
                    entry = MemoryEntry(
                        category="failed_strategy",
                        content=f"Failed strategy for '{step.description}': {strategy}",
                        metadata={
                            "task_id": task.id,
                            "tool_name": step.tool_name or "",
                            "strategy": strategy,
                            "error": step.error or "",
                        },
                        importance=0.6,
                    )
                    await self.memory.store_episodic(entry)
            elif step.status == StepStatus.SUCCEEDED and step.tool_name:
                entry = MemoryEntry(
                    category="successful_pattern",
                    content=f"Successful pattern for '{step.description}': tool={step.tool_name}",
                    metadata={
                        "task_id": task.id,
                        "tool_name": step.tool_name,
                        "description": step.description,
                    },
                    importance=0.7,
                )
                await self.memory.store_episodic(entry)

    def get_status(self) -> dict:
        """Return current agent status."""
        cb_states = {}
        if self.escalation:
            cb_states = self.escalation.get_circuit_breaker_states()
        return {
            "running": self._running,
            "paused": self._paused,
            "safety_mode": self._safety_mode.value,
            "active_tasks": len(self._active_tasks),
            "queued_tasks": len(self._task_queue),
            "reasoning_buffer": list(self._reasoning_buffer),
            "circuit_breaker_states": cb_states,
        }
