"""Security — workspace boundary enforcement, permission whitelist, approval flow."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"


@dataclass
class ApprovalRequest:
    """A request for user approval before executing a risky tool."""

    id: str
    tool_name: str
    arguments: dict[str, Any]
    risk_level: RiskLevel
    reason: str
    status: ApprovalStatus = ApprovalStatus.PENDING


# ── Permission Whitelist ────────────────────────────────────

# Maps tool name → (risk_level, requires_approval_for_auto)
# The auto_approve_risk_level in Settings determines which levels skip approval.
TOOL_PERMISSIONS: dict[str, tuple[RiskLevel, str]] = {
    "list_files": (RiskLevel.LOW, "Read-only directory listing"),
    "search_code": (RiskLevel.LOW, "Read-only code search"),
    "read_file": (RiskLevel.LOW, "Read-only file access within workspace"),
    "git_diff": (RiskLevel.LOW, "Read-only git diff"),
    "run_tests": (RiskLevel.MEDIUM, "Executes shell commands — may consume resources"),
    "write_patch": (RiskLevel.HIGH, "Writes or modifies files in the workspace"),
}

ALLOWED_TOOLS: set[str] = set(TOOL_PERMISSIONS.keys())


def get_tool_risk(tool_name: str) -> RiskLevel:
    """Return the risk level for a tool name.

    Raises ValueError if the tool is not in the whitelist.
    """
    if tool_name not in TOOL_PERMISSIONS:
        raise ValueError(f"Tool '{tool_name}' is not in the permission whitelist.")
    return TOOL_PERMISSIONS[tool_name][0]


def is_tool_allowed(tool_name: str) -> bool:
    """Check if a tool name is in the allowed whitelist."""
    return tool_name in ALLOWED_TOOLS


def needs_approval(tool_name: str, auto_approve_risk: RiskLevel) -> bool:
    """Return True if `tool_name` requires manual approval given the auto-approve
    threshold in settings.

    Example: if auto_approve_risk = LOW, then MEDIUM and HIGH tools need approval.
    """
    risk = get_tool_risk(tool_name)
    risk_order = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
    threshold = risk_order.get(auto_approve_risk, 0)
    return risk_order[risk] > threshold
