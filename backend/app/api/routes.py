"""REST API routes — task submission, SSE streaming, status query."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from app.api.schemas import (
    ApprovalAction,
    ApprovalResponse,
    TaskListItem,
    TaskRequest,
    TaskResponse,
)
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["tasks"])

# In-memory task store (replaced by DB in production)
_tasks: dict[str, dict[str, Any]] = {}
_approvals: dict[str, dict[str, Any]] = {}
_task_refs: dict[str, asyncio.Task] = {}  # Track background tasks for cancellation

# Timeouts (seconds)
TASK_EXECUTION_TIMEOUT = 300  # 5 minutes max for a single task
SSE_MAX_POLL_SECONDS = 360    # 6 minutes max for SSE connection


# ── Helpers ────────────────────────────────────────────────

def _task_id() -> str:
    return f"task-{uuid.uuid4().hex[:12]}"


async def _run_task_and_stream(task_id: str, req: TaskRequest) -> None:
    """Execute a task and push SSE events into the task's event queue.

    Wrapped in asyncio.wait_for to enforce a hard timeout.
    """
    events: list[dict[str, Any]] = _tasks[task_id].setdefault("events", [])
    approval_queue: list[dict[str, Any]] = _tasks[task_id].setdefault("pending_approvals", [])

    def _emit(event_type: str, data: dict[str, Any]) -> None:
        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        events.append(event)

    async def _execute() -> None:
        """Inner coroutine — the actual task logic."""
        _emit("progress", {"message": "Starting task...", "percent": 5})

        settings = get_settings()

        if req.use_orchestrator:
            from app.agents.graph import run_orchestrator_agent

            _emit("progress", {"message": "Orchestrator initializing sub-agents...", "percent": 10})

            result = await run_orchestrator_agent(
                task=req.task,
                workspace_root=req.workspace_root,
                auto_approve_risk=req.auto_approve_risk,
            )

            # Emit phases as they complete
            for i, phase in enumerate(result.get("phases", [])):
                _emit("progress", {
                    "message": f"Phase: {phase.get('phase', '?')} — {phase.get('status', '?')}",
                    "percent": 20 + (i * 20),
                })

            # Emit tool results
            for tr in result.get("tool_results", []):
                _emit("tool_call", tr)

            # Emit approvals
            for apr in result.get("approvals", []):
                _emit("approval_required", apr)
                approval_queue.append(apr)

            # If there are pending approvals, wait briefly (in real impl, this would block)
            if approval_queue:
                _emit("progress", {"message": f"Waiting for {len(approval_queue)} approval(s)...", "percent": 80})

            _emit("summary", {
                "changes": result.get("final_summary", ""),
                "phases": result.get("phases", []),
            })

            _tasks[task_id]["result"] = result
            _tasks[task_id]["status"] = "completed"

        else:
            from app.agents.graph import run_agent
            from app.memory.short_term import AgentState

            _emit("progress", {"message": "Running single-agent workflow...", "percent": 10})

            final_state = await run_agent(
                task=req.task,
                workspace_root=req.workspace_root,
                max_iterations=req.max_iterations,
            )

            _emit("plan", {"steps": final_state.get("plan", [])})

            for tr in final_state.get("tool_results", []):
                _emit("tool_call", tr)

            _emit("summary", {
                "changes": final_state.get("final_summary", ""),
                "iterations": final_state.get("iteration", 0),
            })

            _tasks[task_id]["result"] = final_state
            _tasks[task_id]["status"] = "completed"

        _emit("progress", {"message": "Task complete", "percent": 100})
        _emit("done", {"task_id": task_id})

    try:
        await asyncio.wait_for(_execute(), timeout=TASK_EXECUTION_TIMEOUT)
    except asyncio.TimeoutError:
        logger.error("Task %s timed out after %ds", task_id, TASK_EXECUTION_TIMEOUT)
        _emit("error", {"message": f"Task timed out after {TASK_EXECUTION_TIMEOUT}s"})
        _tasks[task_id]["status"] = "failed"
        _tasks[task_id]["error"] = f"Timeout after {TASK_EXECUTION_TIMEOUT}s"
        _emit("done", {"task_id": task_id})
    except Exception as exc:
        logger.exception("Task %s failed", task_id)
        _emit("error", {"message": str(exc)})
        _tasks[task_id]["status"] = "failed"
        _tasks[task_id]["error"] = str(exc)
        _emit("done", {"task_id": task_id})
    finally:
        _task_refs.pop(task_id, None)


# ── Routes ─────────────────────────────────────────────────

@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(req: TaskRequest) -> dict[str, Any]:
    """Submit a new coding task.  Returns immediately with task_id; execution is async."""
    task_id = _task_id()
    _tasks[task_id] = {
        "task_id": task_id,
        "task": req.task,
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "events": [],
        "pending_approvals": [],
    }

    # Launch in background, track the task for lifecycle management
    bg_task = asyncio.create_task(_run_task_and_stream(task_id, req))
    _task_refs[task_id] = bg_task

    def _on_done(t: asyncio.Task) -> None:
        """Callback: catch unhandled exceptions in the background task."""
        try:
            t.result()
        except asyncio.CancelledError:
            logger.warning("Task %s was cancelled", task_id)
        except Exception as exc:
            logger.exception("Task %s raised unhandled exception: %s", task_id, exc)
            _tasks[task_id].setdefault("events", []).append({
                "type": "error",
                "data": {"message": f"Unhandled error: {exc}"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            _tasks[task_id]["status"] = "failed"
            _tasks[task_id]["error"] = str(exc)

    bg_task.add_done_callback(_on_done)

    return {
        "task_id": task_id,
        "status": "running",
        "task": req.task,
        "phases": [],
        "final_summary": "",
        "error": None,
        "duration_ms": 0.0,
        "approvals": [],
        "tool_results": [],
    }


@router.get("/tasks/{task_id}/stream")
async def stream_task(task_id: str):
    """SSE endpoint — stream task progress events to the frontend.

    Has a maximum poll duration; emits a timeout error if the task
    doesn't complete within SSE_MAX_POLL_SECONDS.
    """
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        start_time = datetime.now(timezone.utc)
        sent_count = 0
        while True:
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            if elapsed > SSE_MAX_POLL_SECONDS:
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {"message": f"Task monitoring timed out after {SSE_MAX_POLL_SECONDS}s"},
                        ensure_ascii=False,
                    ),
                }
                break

            events: list[dict] = _tasks[task_id].get("events", [])
            # Send new events
            while sent_count < len(events):
                event = events[sent_count]
                yield {
                    "event": event["type"],
                    "data": json.dumps(event["data"], ensure_ascii=False),
                }
                sent_count += 1

            # Check if task is done
            status = _tasks[task_id].get("status")
            if status in ("completed", "failed"):
                if sent_count <= len(events):
                    yield {
                        "event": "done" if status == "completed" else "error",
                        "data": json.dumps({"task_id": task_id}),
                    }
                break

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str) -> dict[str, Any]:
    """Get the current status and results of a task."""
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    t = _tasks[task_id]
    result = t.get("result", {})

    return {
        "task_id": task_id,
        "status": t.get("status", "unknown"),
        "task": t.get("task", ""),
        "phases": result.get("phases", []),
        "final_summary": result.get("final_summary", ""),
        "error": t.get("error"),
        "duration_ms": result.get("duration_ms", 0.0),
        "approvals": result.get("approvals", []),
        "tool_results": result.get("tool_results", []),
    }


@router.get("/tasks", response_model=list[TaskListItem])
async def list_tasks() -> list[dict[str, Any]]:
    """List all tasks (most recent first)."""
    items = []
    for tid, t in sorted(_tasks.items(), key=lambda x: x[1].get("created_at", ""), reverse=True):
        items.append({
            "task_id": tid,
            "task": t.get("task", "")[:120],
            "status": t.get("status", "unknown"),
            "created_at": t.get("created_at", ""),
            "duration_ms": t.get("result", {}).get("duration_ms", 0.0),
        })
    return items


@router.post("/tasks/{task_id}/approve")
async def approve_task(task_id: str, action: ApprovalAction) -> dict[str, Any]:
    """Approve or reject a pending approval request."""
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    t = _tasks[task_id]
    pending = t.get("pending_approvals", [])

    for apr in pending:
        if apr.get("id") == action.approval_id:
            if action.action == "approve":
                apr["status"] = "approved"
            elif action.action == "reject":
                apr["status"] = "rejected"
            else:
                raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")

            t["events"].append({
                "type": "approval_resolved",
                "data": apr,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return {"status": "ok", "approval": apr}

    raise HTTPException(status_code=404, detail="Approval not found")
