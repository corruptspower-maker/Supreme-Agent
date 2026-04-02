"""Core Pydantic data models for the Executive Agent."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(tz=timezone.utc)

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Status of a task in the agent's pipeline."""

    PENDING = "pending"
    PLANNING = "planning"
    EXECUTING = "executing"
    ESCALATED = "escalated"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RiskLevel(str, Enum):
    """Risk classification for actions."""

    SAFE = "safe"
    MODERATE = "moderate"
    DANGEROUS = "dangerous"
    FORBIDDEN = "forbidden"


class StepStatus(str, Enum):
    """Status of an individual plan step."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    ESCALATED = "escalated"


class EscalationTier(str, Enum):
    """Available escalation tiers."""

    TIER1_COPILOT = "tier1_copilot"
    TIER2_CLAUDE_CODE = "tier2_claude_code"
    TIER3_CLINE = "tier3_cline"


class EscalationReason(str, Enum):
    """Reasons for escalating to a higher-capability system."""

    REPEATED_FAILURE = "repeated_failure"
    COMPLEXITY_EXCEEDED = "complexity_exceeded"
    CONFIDENCE_LOW = "confidence_low"
    CODE_GENERATION = "code_generation"
    DEBUGGING = "debugging"
    ARCHITECTURE_NEEDED = "architecture_needed"
    REASONING_DEPTH = "reasoning_depth"
    CONTEXT_OVERFLOW = "context_overflow"
    TIMEOUT = "timeout"
    USER_REQUEST = "user_request"
    MISSING_MCP_TOOL = "missing_mcp_tool"


class SafetyMode(str, Enum):
    """Safety enforcement level."""

    FULL = "full"
    LIGHT_BYPASS = "light_bypass"
    MEDIUM_BYPASS = "medium_bypass"
    SEVERE_LOCKED = "severe_locked"


class UserRequest(BaseModel):
    """A request submitted by the user."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    text: str
    source: str = "cli"
    timestamp: datetime = Field(default_factory=_utcnow)
    context: dict = Field(default_factory=dict)


class PlanStep(BaseModel):
    """A single step in an execution plan."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    description: str
    tool_name: Optional[str] = None
    tool_args: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3


class Plan(BaseModel):
    """A multi-step execution plan for a task."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    steps: list[PlanStep]
    reasoning: str
    created_at: datetime = Field(default_factory=_utcnow)
    confidence: float = Field(ge=0.0, le=1.0)


class ToolResult(BaseModel):
    """Result returned by a tool after execution."""

    tool_name: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    execution_time_ms: int = 0
    side_effects: list[str] = Field(default_factory=list)


class EscalationRequest(BaseModel):
    """Request to escalate a task to a higher-capability system."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    reason: EscalationReason
    tier: EscalationTier
    task_description: str
    steps_attempted: list[PlanStep]
    errors_encountered: list[str]
    current_code: Optional[str] = None
    context: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)


class EscalationResponse(BaseModel):
    """Response from an escalation tier."""

    request_id: str
    tier_used: EscalationTier
    tool_used: str
    solution: str
    suggested_steps: list[str] = Field(default_factory=list)
    code_changes: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)


class MemoryEntry(BaseModel):
    """A single entry in the agent's memory system."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    category: str
    content: str
    metadata: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    access_count: int = 0


class Task(BaseModel):
    """A top-level task being processed by the agent."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    request: UserRequest
    status: TaskStatus = TaskStatus.PENDING
    plan: Optional[Plan] = None
    results: list[ToolResult] = Field(default_factory=list)
    escalations: list[EscalationRequest] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class AuditEntry(BaseModel):
    """An append-only audit log entry."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=_utcnow)
    action: str
    tool_name: Optional[str] = None
    risk_level: RiskLevel
    user_confirmed: Optional[bool] = None
    input_summary: str
    output_summary: Optional[str] = None
    success: bool
    error: Optional[str] = None


class ScreenshotEntry(BaseModel):
    """A screenshot captured during agent execution."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    image_path: str
    description: str
    timestamp: datetime = Field(default_factory=_utcnow)
    action_taken: Optional[str] = None
