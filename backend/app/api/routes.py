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
SSE_HEARTBEAT_SECONDS = 20    # liveness 'ping' when no events for 20s


# ── Helpers ────────────────────────────────────────────────

def _task_id() -> str:
    return f"task-{uuid.uuid4().hex[:12]}"


# Max characters of the previous report injected into a follow-up prompt.
FOLLOWUP_CONTEXT_CHARS = 8000


def _build_followup_task(question: str, previous: dict[str, Any]) -> str:
    """Build the effective task prompt for a follow-up question.

    Injects the previous task and its final report as context so the agents
    can continue the conversation instead of starting from scratch.
    """
    prev_result = previous.get("result") or {}
    prev_summary = prev_result.get("final_summary", "") or previous.get("error", "")
    prev_task = previous.get("task", "")
    return (
        "这是一个追问任务。用户此前提交过一个任务并拿到了最终报告，"
        "现在用户基于该报告提出了追问，请你围绕报告内容回答。\n\n"
        f"### 之前的任务\n{prev_task}\n\n"
        f"### 之前的最终报告\n{prev_summary[:FOLLOWUP_CONTEXT_CHARS]}\n\n"
        f"### 用户的追问\n{question}\n\n"
        "请基于上述报告回答追问。如果需要查看仓库代码、运行工具来验证，可以正常使用工具。"
    )


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
        _emit("progress", {"message": "任务已接收，正在准备执行…", "percent": 5})

        settings = get_settings()

        if req.use_orchestrator:
            from app.agents.graph import run_orchestrator_agent
            from app.security.approval_gate import ApprovalGate

            _emit("progress", {
                "message": "正在初始化多智能体协作系统（仓库分析师 → 代码实现者 → 代码审查者）…",
                "percent": 10,
            })

            # Real approval gate: blocks the agent loop at each risky tool
            # until the user resolves it via /approve (or it times out).
            gate = ApprovalGate(task_id=task_id, emit=_emit)
            _tasks[task_id]["approval_gate"] = gate

            # Live SSE events (progress + tool_call) are pushed during the
            # run via the emit sink shared with the orchestrator/sub-agents.
            result = await run_orchestrator_agent(
                task=req.task,
                workspace_root=req.workspace_root,
                auto_approve_risk=req.auto_approve_risk,
                approval_gate=gate,
                emit=_emit,
            )

            # Emit the final approval ledger (approved / rejected / auto-approved).
            # The frontend upserts by id, so this updates card statuses.
            for apr in result.get("approvals", []):
                _emit("approval_required", apr)
                approval_queue.append(apr)

            _emit("summary", {
                "changes": result.get("final_summary", ""),
                "phases": result.get("phases", []),
            })

            _tasks[task_id]["result"] = result
            _tasks[task_id]["status"] = "completed"

        else:
            from app.agents.graph import run_agent
            from app.memory.short_term import AgentState

            _emit("progress", {"message": "正在运行单智能体工作流…", "percent": 10})

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

        _emit("progress", {"message": "任务完成，报告已生成", "percent": 100})
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

    # Follow-up: inject the previous task's report as context.
    effective_task = req.task
    followup_of = req.followup_of
    if followup_of:
        previous = _tasks.get(followup_of)
        if previous is None:
            raise HTTPException(
                status_code=404,
                detail=f"Follow-up target task '{followup_of}' not found",
            )
        effective_task = _build_followup_task(req.task, previous)

    _tasks[task_id] = {
        "task_id": task_id,
        "task": req.task,
        "effective_task": effective_task,
        "followup_of": followup_of,
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "events": [],
        "pending_approvals": [],
    }

    # Execute the augmented task (includes previous report for follow-ups).
    effective_req = req.model_copy(update={"task": effective_task})

    # Launch in background, track the task for lifecycle management
    bg_task = asyncio.create_task(_run_task_and_stream(task_id, effective_req))
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


@router.get("/browse")
async def browse_directories(path: str | None = None) -> dict[str, Any]:
    """List directories on the host filesystem for the frontend's folder picker.

    Single-user local tool. Without `path`, returns the drive letters on
    Windows or the filesystem root elsewhere. Only subdirectories are listed.
    """
    import os
    import string

    if not path:
        if os.name == "nt":
            drives = []
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.isdir(drive):
                    drives.append({"name": drive, "path": drive, "type": "dir"})
            return {"path": "", "parent": None, "entries": drives}
        path = "/"

    p = os.path.abspath(path)
    if not os.path.isdir(p):
        raise HTTPException(status_code=400, detail=f"不是有效的目录: {p}")

    try:
        names = os.listdir(p)
    except (PermissionError, OSError) as exc:
        raise HTTPException(status_code=403, detail=f"无法读取目录: {exc}")

    entries = []
    for name in sorted(names, key=str.lower):
        full = os.path.join(p, name)
        if os.path.isdir(full):
            entries.append({"name": name, "path": full, "type": "dir"})

    parent = os.path.dirname(p)
    if parent == p:
        # At a filesystem root (e.g. a Windows drive root): going up returns
        # to the top-level listing (drive letters).
        parent = ""
    return {"path": p, "parent": parent, "entries": entries}


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
        last_event_time = start_time
        while True:
            now = datetime.now(timezone.utc)
            elapsed = (now - start_time).total_seconds()
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
                last_event_time = now

            # Check if task is done
            status = _tasks[task_id].get("status")
            if status in ("completed", "failed"):
                if sent_count <= len(events):
                    yield {
                        "event": "done" if status == "completed" else "error",
                        "data": json.dumps({"task_id": task_id}),
                    }
                break

            # Liveness heartbeat: emit a 'ping' event when nothing has been
            # sent recently. LLM calls can take up to 90s per round, which
            # would otherwise trip the frontend's idle timeout.
            if (now - last_event_time).total_seconds() >= SSE_HEARTBEAT_SECONDS:
                yield {
                    "event": "ping",
                    "data": json.dumps({"t": now.isoformat()}),
                }
                last_event_time = now

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
    """Approve or reject a pending approval request.

    Resolves the blocking ApprovalGate so the paused agent loop can proceed
    (or skip the denied tool and continue).
    """
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    if action.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")

    approved = action.action == "approve"

    t = _tasks[task_id]
    gate = t.get("approval_gate")
    if gate is not None:
        resolved = gate.resolve(action.approval_id, approved)
        if not resolved:
            raise HTTPException(
                status_code=404,
                detail="Approval not found or already resolved",
            )
        # Also reflect the resolution in the task event log / pending list.
        resolved_apr = {
            "id": action.approval_id,
            "status": "approved" if approved else "rejected",
        }
        t["events"].append({
            "type": "approval_resolved",
            "data": resolved_apr,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return {"status": "ok", "approval": resolved_apr}

    # Fallback: single-agent path has no gate — mutate the legacy pending list.
    pending = t.get("pending_approvals", [])
    for apr in pending:
        if apr.get("id") == action.approval_id:
            apr["status"] = "approved" if approved else "rejected"
            t["events"].append({
                "type": "approval_resolved",
                "data": apr,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return {"status": "ok", "approval": apr}

    raise HTTPException(status_code=404, detail="Approval not found")
