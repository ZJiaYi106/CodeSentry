"""Short-term memory — agent state management within a single task session.

Uses LangGraph's state graph annotations.  State is ephemeral — cleared on task completion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from langchain_core.messages import BaseMessage


class NextAction(str, Enum):
    CONTINUE = "continue"
    REPLAN = "replan"
    FINISH = "finish"


@dataclass
class PlanStep:
    """A single step in the agent's execution plan."""

    id: str
    description: str
    tool_name: str | None = None  # None = LLM-only reasoning step
    tool_args: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending | running | completed | failed
    result_summary: str = ""


@dataclass
class AgentState:
    """Full state for a single task execution.

    Passed between LangGraph nodes.  This is the "short-term memory."
    """

    task: str
    workspace_root: str
    messages: list[BaseMessage] = field(default_factory=list)
    plan: list[PlanStep] = field(default_factory=list)
    current_step_index: int = 0
    observations: list[str] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 15
    next_action: str = NextAction.CONTINUE.value
    final_summary: str = ""
    error: str | None = None
    approval_required: bool = False
    pending_approval_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict for SSE / API responses."""
        return {
            "task": self.task,
            "iteration": self.iteration,
            "next_action": self.next_action,
            "plan": [
                {
                    "id": s.id,
                    "description": s.description,
                    "tool_name": s.tool_name,
                    "status": s.status,
                    "result_summary": s.result_summary,
                }
                for s in self.plan
            ],
            "observations": self.observations[-5:],  # last 5
            "tool_results": self.tool_results[-10:],
            "error": self.error,
            "approval_required": self.approval_required,
        }

    @property
    def current_step(self) -> PlanStep | None:
        """Return the current plan step, or None."""
        if 0 <= self.current_step_index < len(self.plan):
            return self.plan[self.current_step_index]
        return None

    @property
    def is_done(self) -> bool:
        return self.next_action == NextAction.FINISH.value or self.iteration >= self.max_iterations

    @property
    def has_error(self) -> bool:
        return self.error is not None

    def add_observation(self, text: str) -> None:
        self.observations.append(text)
        if self.current_step:
            self.current_step.result_summary = text[:300]

    def add_tool_result(self, result: dict[str, Any]) -> None:
        self.tool_results.append(result)
