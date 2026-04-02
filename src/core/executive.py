"""Executive Agent — main orchestrator for the agent system."""

from __future__ import annotations

import asyncio
import json
import socket
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from src.core.models import (
    Task, TaskStatus, UserRequest, SafetyMode,
)
from src.utils.config import load_config, get_full_config
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
        """Initialize all subsystems."""
        logger.info("Subsystems initialized")

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

    async def _process_task(self, task: Task) -> None:
        """Process a single task through plan → execute → memory → report."""
        task.started_at = datetime.utcnow()
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
                task = await self.executor.execute_plan(task)
            else:
                task.status = TaskStatus.COMPLETED
            
            if self.memory:
                await self.memory.store_task_result(task)
            
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
                "saved_at": datetime.utcnow().isoformat(),
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
        logger.info("Agent shutdown complete")

    def get_status(self) -> dict:
        """Return current agent status."""
        return {
            "running": self._running,
            "paused": self._paused,
            "safety_mode": self._safety_mode.value,
            "active_tasks": len(self._active_tasks),
            "queued_tasks": len(self._task_queue),
            "reasoning_buffer": list(self._reasoning_buffer),
        }
