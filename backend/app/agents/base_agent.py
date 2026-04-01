"""Base class for sub-agents — every sub-agent has a restricted tool set and role."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class SubAgentResult:
    """Structured result from a sub-agent invocation."""

    agent_name: str
    success: bool
    output: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    duration_ms: float = 0.0


class BaseSubAgent:
    """Abstract base for sub-agents.

    Each sub-agent:
      - Has a name and role description (system prompt)
      - Gets a restricted list of tool NAMES that it may call
      - Reports results back to the Orchestrator
      - Cannot directly execute HIGH-risk tools without Orchestrator approval
    """

    name: str = "base"
    description: str = ""
    allowed_tools: list[str] = []  # tool names this agent may use

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self._registry = ToolRegistry(workspace_root)

    @property
    def tools(self) -> list[Any]:
        """Return the tool instances this agent is allowed to use."""
        return [
            self._registry.get(name)
            for name in self.allowed_tools
            if name in self._registry
        ]

    @property
    def system_prompt(self) -> str:
        """Return the system prompt for this agent. Override in subclasses."""
        return (
            f"You are {self.name}, a sub-agent of CodeSentry. "
            f"{self.description}\n\n"
            f"You may only use the following tools: {', '.join(self.allowed_tools)}. "
            f"Do not attempt to use other tools. "
            f"Report your findings clearly and concisely."
        )

    async def run(self, task_context: str) -> SubAgentResult:
        """Execute the sub-agent's task and return a structured result.

        In a full implementation this would call the LLM with the agent's
        system prompt and restricted tool set.  For now we provide a
        deterministic fallback that explains what the agent WOULD do.
        """
        import time

        start = time.perf_counter()
        logger.info("SUB-AGENT | %s starting (tools=%s)", self.name, self.allowed_tools)

        output = self._fallback_run(task_context)
        duration = (time.perf_counter() - start) * 1000

        return SubAgentResult(
            agent_name=self.name,
            success=True,
            output=output,
            duration_ms=duration,
        )

    def _fallback_run(self, task_context: str) -> str:
        """Deterministic fallback — describes what this agent would analyze.

        Override in subclasses for richer behavior.
        """
        return (
            f"[{self.name}] Would analyze task: {task_context[:200]}\n"
            f"Allowed tools: {', '.join(self.allowed_tools)}\n"
            f"Workspace: {self.workspace_root}"
        )
