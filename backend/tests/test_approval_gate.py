"""Tests for the approval gate — the real execution-time interceptor.

These verify the behaviour that was previously only aspirational: that a
risky tool is NOT executed until an approval is resolved, and that the
auto-approve fallback is explicit and auditable rather than silent.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.security.approval_gate import AutoApproveGate, ApprovalDecision, ApprovalGate
from app.security.permissions import ApprovalStatus, RiskLevel


# ── AutoApproveGate ────────────────────────────────────────

class TestAutoApproveGate:
    @pytest.mark.asyncio
    async def test_immediately_approves(self):
        gate = AutoApproveGate()
        decision = await gate.request(
            "write_patch", {"file_path": "a.py", "content": "x"},
            "Implementer", RiskLevel.HIGH,
        )
        assert decision.approved is True
        assert decision.status == ApprovalStatus.AUTO_APPROVED
        assert "自动放行" in decision.reason or "auto" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_records_approval_as_auto_approved(self):
        gate = AutoApproveGate()
        await gate.request("write_patch", {}, "Implementer", RiskLevel.HIGH)
        await gate.request("run_tests", {"command": "pytest"}, "Reviewer", RiskLevel.MEDIUM)
        assert len(gate.approvals) == 2
        assert all(a.status == ApprovalStatus.AUTO_APPROVED for a in gate.approvals)
        assert gate.approvals[0].tool_name == "write_patch"
        assert gate.approvals[1].tool_name == "run_tests"

    def test_resolve_is_noop(self):
        gate = AutoApproveGate()
        # Nothing is ever pending, so resolve always returns False.
        assert gate.resolve("apr-0001", True) is False


# ── ApprovalGate (blocking) ────────────────────────────────

class TestApprovalGate:
    @pytest.mark.asyncio
    async def test_blocks_until_approved(self):
        gate = ApprovalGate(task_id="t1")
        req_task = asyncio.create_task(
            gate.request("write_patch", {"file_path": "a.py"}, "Implementer", RiskLevel.HIGH)
        )

        # Let the request register.
        await asyncio.sleep(0.05)
        assert len(gate.approvals) == 1
        assert gate.approvals[0].status == ApprovalStatus.PENDING

        # Not yet resolved.
        assert not req_task.done()

        gate.resolve(gate.approvals[0].id, approved=True)
        decision = await asyncio.wait_for(req_task, timeout=2)
        assert decision.approved is True
        assert decision.status == ApprovalStatus.APPROVED
        assert gate.approvals[0].status == ApprovalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_blocks_until_rejected(self):
        gate = ApprovalGate(task_id="t2")
        req_task = asyncio.create_task(
            gate.request("run_tests", {"command": "pytest"}, "Reviewer", RiskLevel.MEDIUM)
        )
        await asyncio.sleep(0.05)
        gate.resolve(gate.approvals[0].id, approved=False)

        decision = await asyncio.wait_for(req_task, timeout=2)
        assert decision.approved is False
        assert decision.status == ApprovalStatus.REJECTED
        assert "rejected" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_resolve_unknown_id_returns_false(self):
        gate = ApprovalGate(task_id="t3")
        assert gate.resolve("does-not-exist", True) is False

    @pytest.mark.asyncio
    async def test_double_resolve_returns_false(self):
        gate = ApprovalGate(task_id="t4")
        req_task = asyncio.create_task(
            gate.request("write_patch", {}, "Implementer", RiskLevel.HIGH)
        )
        await asyncio.sleep(0.05)
        assert gate.resolve(gate.approvals[0].id, True) is True
        await asyncio.wait_for(req_task, timeout=2)
        # Already resolved — second resolve must be a no-op.
        assert gate.resolve(gate.approvals[0].id, True) is False

    @pytest.mark.asyncio
    async def test_timeout_denies(self):
        gate = ApprovalGate(task_id="t5", timeout_seconds=0.1, heartbeat_seconds=999)
        decision = await gate.request(
            "write_patch", {}, "Implementer", RiskLevel.HIGH
        )
        assert decision.approved is False
        assert decision.status == ApprovalStatus.REJECTED
        assert "timed out" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_emits_approval_required_event(self):
        emitted: list[tuple[str, dict[str, Any]]] = []
        gate = ApprovalGate(task_id="t6", emit=lambda t, d: emitted.append((t, d)))
        req_task = asyncio.create_task(
            gate.request("write_patch", {"file_path": "a.py"}, "Implementer", RiskLevel.HIGH)
        )
        await asyncio.sleep(0.05)
        gate.resolve(gate.approvals[0].id, True)
        await req_task

        types = [t for t, _ in emitted]
        assert "approval_required" in types
        req_evt = next(d for t, d in emitted if t == "approval_required")
        assert req_evt["tool"] == "write_patch"
        assert req_evt["status"] == "pending"
        assert req_evt["arguments"] == {"file_path": "a.py"}
        assert req_evt["risk"] == "high"


# ── End-to-end: gate actually prevents execution ───────────

class TestGatePreventsExecution:
    """A gated write must NOT touch the filesystem until approved."""

    @pytest.mark.asyncio
    async def test_write_blocked_until_approved(self, tmp_path: Path):
        from app.tools.write_patch import WritePatchTool

        tool = WritePatchTool(str(tmp_path))
        gate = ApprovalGate(task_id="t7")
        target = tmp_path / "out.txt"

        async def call() -> Any:
            # Simulate what BaseSubAgent._llm_call does: gate then run.
            decision = await gate.request(
                "write_patch", {"file_path": "out.txt", "content": "hi"},
                "Implementer", RiskLevel.HIGH,
            )
            if not decision.approved:
                return ("denied", decision.reason)
            return await tool.run(file_path="out.txt", content="hi")

        req_task = asyncio.create_task(call())
        await asyncio.sleep(0.05)

        # While pending: file must not exist.
        assert not target.exists()

        gate.resolve(gate.approvals[0].id, True)
        result = await asyncio.wait_for(req_task, timeout=2)
        assert result[0] if isinstance(result, tuple) else result.success
        assert target.read_text() == "hi"

    @pytest.mark.asyncio
    async def test_write_skipped_when_rejected(self, tmp_path: Path):
        from app.tools.write_patch import WritePatchTool

        tool = WritePatchTool(str(tmp_path))
        gate = ApprovalGate(task_id="t8")
        target = tmp_path / "out.txt"

        async def call() -> Any:
            decision = await gate.request(
                "write_patch", {"file_path": "out.txt", "content": "hi"},
                "Implementer", RiskLevel.HIGH,
            )
            if not decision.approved:
                return ("denied", decision.reason)
            return await tool.run(file_path="out.txt", content="hi")

        req_task = asyncio.create_task(call())
        await asyncio.sleep(0.05)
        gate.resolve(gate.approvals[0].id, False)
        result = await asyncio.wait_for(req_task, timeout=2)

        # Rejected → never executed the write.
        assert result == ("denied", "rejected by user") or (
            isinstance(result, tuple) and result[0] == "denied"
        )
        assert not target.exists()
