"""Pydantic models for API requests and responses."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


# ── Request ────────────────────────────────────────────────

class TaskRequest(BaseModel):
    """Request to start a new coding task."""

    task: str = Field(..., description="The user's coding task description", min_length=1, max_length=10000)
    workspace_root: str = Field(default="/workspace", description="Path to the workspace")
    auto_approve_risk: str = Field(default="low", description="Auto-approve risk level: low, medium, high, none")
    max_iterations: int = Field(default=15, ge=1, le=100, description="Max agent loop iterations")
    use_orchestrator: bool = Field(default=True, description="Use multi-agent orchestrator instead of single agent")


class ApprovalAction(BaseModel):
    """User action on an approval request."""

    approval_id: str = Field(..., description="The approval request ID")
    action: str = Field(..., description="'approve' or 'reject'")


# ── Response ───────────────────────────────────────────────

class PlanStepResponse(BaseModel):
    id: str
    description: str
    tool_name: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"
    result_summary: str = ""


class ToolCallResponse(BaseModel):
    tool: str
    success: bool
    data: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    risk_level: str = "low"


class ApprovalResponse(BaseModel):
    id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    risk_level: str
    reason: str
    status: str = "pending"


class TimelineEvent(BaseModel):
    type: str  # plan | tool_call | observation | reflection | approval | summary | error | done
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TaskResponse(BaseModel):
    """Response after task completion or status check."""

    task_id: str
    status: str  # running | completed | failed
    task: str
    phases: list[dict[str, Any]] = Field(default_factory=list)
    final_summary: str = ""
    error: str | None = None
    duration_ms: float = 0.0
    approvals: list[ApprovalResponse] = Field(default_factory=list)
    tool_results: list[ToolCallResponse] = Field(default_factory=list)


class TaskListItem(BaseModel):
    """Summary item for task listing."""

    task_id: str
    task: str
    status: str
    created_at: str
    duration_ms: float = 0.0


class HealthResponse(BaseModel):
    status: str
    version: str
    provider: str = ""
    model: str = ""
