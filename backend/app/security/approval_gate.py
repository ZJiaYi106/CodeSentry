"""Approval gate — the real execution-time interceptor for risky tools.

This is what makes CodeSentry's "approval" an actual gate rather than
post-hoc bookkeeping.  Before a sub-agent executes a tool whose risk level
exceeds the auto-approve threshold, the agent calls ``gate.request(...)``.

Two implementations:

- :class:`ApprovalGate`   — used over HTTP/SSE.  Blocks the agent loop until
  the user resolves the request via the ``/approve`` endpoint (or it times
  out).  Emits ``approval_required`` SSE events and periodic heartbeats so
  the SSE stream stays alive while the user deliberates.
- :class:`AutoApproveGate` — used when no human is in the loop (demos,
  direct ``Orchestrator`` usage, tests).  Immediately approves, but records
  every decision as ``AUTO_APPROVED`` so the auto-approval is visible and
  auditable rather than silent.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.security.permissions import ApprovalRequest, ApprovalStatus, RiskLevel

logger = logging.getLogger(__name__)


@dataclass
class ApprovalDecision:
    """Outcome of an approval request."""

    approved: bool
    status: ApprovalStatus
    id: str
    reason: str


# A sink for SSE events: (event_type, data_dict) -> None.  Sync; routes.py
# appends to an in-memory event list consumed by the SSE poller.
EmitFn = Callable[[str, dict[str, Any]], None]


class _BaseGate:
    """Shared bookkeeping: the list of approval requests raised so far."""

    def __init__(self) -> None:
        self.approvals: list[ApprovalRequest] = []

    def _new_request(
        self, tool_name: str, arguments: dict[str, Any], agent_name: str, risk: RiskLevel
    ) -> ApprovalRequest:
        req = ApprovalRequest(
            id=f"apr-{len(self.approvals) + 1:04d}",
            tool_name=tool_name,
            arguments=arguments,
            risk_level=risk,
            reason=f"智能体「{agent_name}」请求使用工具「{tool_name}」，需要你的批准后才能执行",
        )
        self.approvals.append(req)
        return req


class ApprovalGate(_BaseGate):
    """Blocking approval gate for the HTTP/SSE path.

    ``request()`` emits an ``approval_required`` event and then awaits the
    matching ``resolve()`` call (made by the ``/approve`` endpoint).  While
    waiting it emits periodic ``progress`` heartbeats so the frontend's SSE
    idle-timeout does not fire.
    """

    def __init__(
        self,
        task_id: str,
        emit: EmitFn | None = None,
        timeout_seconds: float = 280.0,
        heartbeat_seconds: float = 15.0,
    ) -> None:
        super().__init__()
        self.task_id = task_id
        self._emit = emit
        self._timeout = timeout_seconds
        self._heartbeat = heartbeat_seconds
        self._events: dict[str, asyncio.Event] = {}
        self._results: dict[str, bool] = {}

    async def request(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        agent_name: str,
        risk: RiskLevel,
    ) -> ApprovalDecision:
        """Ask for approval and block until resolved or timed out."""
        req = self._new_request(tool_name, arguments, agent_name, risk)
        ev = asyncio.Event()
        self._events[req.id] = ev

        logger.info(
            "APPROVAL | request %s tool=%s risk=%s agent=%s",
            req.id, tool_name, risk.value, agent_name,
        )

        self._emit_sse("approval_required", {
            "id": req.id,
            "tool": tool_name,
            "arguments": arguments,
            "risk": risk.value,
            "reason": req.reason,
            "status": ApprovalStatus.PENDING.value,
        })

        # Heartbeat: keep the SSE stream alive while the user decides.
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(req.id))

        try:
            await asyncio.wait_for(ev.wait(), timeout=self._timeout)
        except asyncio.TimeoutError:
            logger.warning("APPROVAL | %s timed out after %ss — denying", req.id, self._timeout)
            self._set_status(req, ApprovalStatus.REJECTED)
            return ApprovalDecision(
                approved=False,
                status=ApprovalStatus.REJECTED,
                id=req.id,
                reason=f"approval timed out after {self._timeout}s",
            )
        finally:
            heartbeat_task.cancel()

        approved = self._results.get(req.id, False)
        self._set_status(req, ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED)

        self._emit_sse("approval_resolved", {
            "id": req.id,
            "tool": tool_name,
            "status": req.status.value,
        })

        return ApprovalDecision(
            approved=approved,
            status=req.status,
            id=req.id,
            reason="approved by user" if approved else "rejected by user",
        )

    def resolve(self, approval_id: str, approved: bool) -> bool:
        """Resolve a pending request.  Returns False if id is unknown/already resolved."""
        ev = self._events.get(approval_id)
        if ev is None or ev.is_set():
            return False
        self._results[approval_id] = approved
        ev.set()
        logger.info("APPROVAL | %s resolved approved=%s", approval_id, approved)
        return True

    # ── internals ──────────────────────────────────────────

    async def _heartbeat_loop(self, approval_id: str) -> None:
        """Emit periodic progress events while a request is pending."""
        try:
            while True:
                await asyncio.sleep(self._heartbeat)
                self._emit_sse("progress", {
                    "message": f"等待审批 ({approval_id})…",
                    "percent": 80,
                })
        except asyncio.CancelledError:
            pass

    def _emit_sse(self, event_type: str, data: dict[str, Any]) -> None:
        if self._emit is None:
            return
        try:
            self._emit(event_type, data)
        except Exception as exc:  # never let SSE plumbing break the gate
            logger.debug("APPROVAL | emit failed: %s", exc)

    def _set_status(self, req: ApprovalRequest, status: ApprovalStatus) -> None:
        req.status = status


class AutoApproveGate(_BaseGate):
    """Non-blocking gate: immediately approves everything, visibly.

    Used for demos, direct ``Orchestrator`` usage, and tests where there is
    no human to resolve approvals.  Each decision is recorded as
    ``AUTO_APPROVED`` so the auto-approval is auditable, not silent.
    """

    async def request(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        agent_name: str,
        risk: RiskLevel,
    ) -> ApprovalDecision:
        req = self._new_request(tool_name, arguments, agent_name, risk)
        req.status = ApprovalStatus.AUTO_APPROVED
        logger.info(
            "APPROVAL | auto-approve %s tool=%s risk=%s agent=%s (no human in the loop)",
            req.id, tool_name, risk.value, agent_name,
        )
        return ApprovalDecision(
            approved=True,
            status=ApprovalStatus.AUTO_APPROVED,
            id=req.id,
            reason="无人审批-自动放行",
        )

    def resolve(self, approval_id: str, approved: bool) -> bool:  # pragma: no cover - no-op
        # Nothing is ever pending under AutoApproveGate, so there is nothing to resolve.
        return False
