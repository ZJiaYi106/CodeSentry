"""Tests for security module — permissions, approvals."""

from __future__ import annotations

import pytest

from app.security.permissions import (
    ALLOWED_TOOLS,
    ApprovalRequest,
    ApprovalStatus,
    RiskLevel,
    get_tool_risk,
    is_tool_allowed,
    needs_approval,
)


class TestPermissionWhitelist:
    def test_all_six_tools_allowed(self):
        for name in ["list_files", "search_code", "read_file", "write_patch", "run_tests", "git_diff"]:
            assert is_tool_allowed(name), f"{name} should be allowed"

    def test_unknown_tool_not_allowed(self):
        assert not is_tool_allowed("delete_everything")
        assert not is_tool_allowed("sudo_rm_rf")

    def test_get_risk_for_all_tools(self):
        assert get_tool_risk("list_files") == RiskLevel.LOW
        assert get_tool_risk("search_code") == RiskLevel.LOW
        assert get_tool_risk("read_file") == RiskLevel.LOW
        assert get_tool_risk("git_diff") == RiskLevel.LOW
        assert get_tool_risk("run_tests") == RiskLevel.MEDIUM
        assert get_tool_risk("write_patch") == RiskLevel.HIGH

    def test_unknown_tool_raises_value_error(self):
        with pytest.raises(ValueError):
            get_tool_risk("bad_tool")


class TestApprovalLogic:
    def test_auto_approve_none(self):
        """With auto_approve=none, all tools need approval."""
        assert needs_approval("list_files", RiskLevel.LOW) is False  # low == low → no
        assert needs_approval("run_tests", RiskLevel.LOW) is True
        assert needs_approval("write_patch", RiskLevel.LOW) is True

    def test_auto_approve_medium(self):
        """With auto_approve=medium, low+medium skip approval."""
        assert needs_approval("list_files", RiskLevel.MEDIUM) is False
        assert needs_approval("run_tests", RiskLevel.MEDIUM) is False
        assert needs_approval("write_patch", RiskLevel.MEDIUM) is True

    def test_auto_approve_high(self):
        """With auto_approve=high, nothing needs approval."""
        assert needs_approval("list_files", RiskLevel.HIGH) is False
        assert needs_approval("run_tests", RiskLevel.HIGH) is False
        assert needs_approval("write_patch", RiskLevel.HIGH) is False


class TestApprovalRequest:
    def test_creates_pending_request(self):
        req = ApprovalRequest(
            id="req-1",
            tool_name="write_patch",
            arguments={"file_path": "test.py", "content": "x=1"},
            risk_level=RiskLevel.HIGH,
            reason="Writing new file",
        )
        assert req.status == ApprovalStatus.PENDING
        assert req.risk_level == RiskLevel.HIGH

    def test_approval_status_transitions(self):
        req = ApprovalRequest(
            id="req-2", tool_name="run_tests",
            arguments={"command": "pytest"},
            risk_level=RiskLevel.MEDIUM,
            reason="Run test suite",
        )
        req.status = ApprovalStatus.APPROVED
        assert req.status == ApprovalStatus.APPROVED
        req.status = ApprovalStatus.REJECTED
        assert req.status == ApprovalStatus.REJECTED
