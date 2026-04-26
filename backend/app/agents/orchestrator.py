"""Central Orchestrator — plans, delegates, approves, and controls quality.

The Orchestrator is the ONLY agent that:
  - Sees the full picture
  - Coordinates sub-agents
  - Grants or denies approval for risky operations
  - Synthesizes final results
  - Enforces the security boundary

Sub-agents (RepoAnalyst, Implementer, Reviewer) have RESTRICTED tool sets
and CANNOT directly execute writes or high-risk commands.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.agents.implementer import Implementer
from app.agents.repo_analyst import RepoAnalyst
from app.agents.reviewer import Reviewer
from app.security.permissions import (
    ApprovalRequest,
    ApprovalStatus,
    RiskLevel,
    get_tool_risk,
    is_tool_allowed,
    needs_approval,
)
from app.audit.logger import log_event

logger = logging.getLogger(__name__)


class OrchestratorPhase(str, Enum):
    ANALYZE = "analyze"
    IMPLEMENT = "implement"
    REVIEW = "review"
    DONE = "done"


@dataclass
class OrchestratorResult:
    """Full result from an orchestrator run."""

    task: str
    success: bool
    phases: list[dict[str, Any]] = field(default_factory=list)
    analyst_result: Any = None
    implementer_result: Any = None
    reviewer_result: Any = None
    approvals: list[ApprovalRequest] = field(default_factory=list)
    final_summary: str = ""
    error: str | None = None
    total_duration_ms: float = 0.0


class Orchestrator:
    """Central coordinator for the CodeSentry multi-agent system.

    Workflow:
      1. ANALYZE  → RepoAnalyst explores the codebase
      2. IMPLEMENT → Implementer proposes changes (writes gated)
      3. REVIEW    → Reviewer validates + runs tests (execution gated)
      4. DONE      → Synthesize results
    """

    def __init__(
        self,
        workspace_root: str,
        auto_approve_risk: RiskLevel = RiskLevel.LOW,
    ):
        self.workspace_root = workspace_root
        self.auto_approve_risk = auto_approve_risk
        self.analyst = RepoAnalyst(workspace_root)
        self.implementer = Implementer(workspace_root)
        self.reviewer = Reviewer(workspace_root)
        self.approvals: list[ApprovalRequest] = []

    # ── Sub-agent tool restrictions ────────────────────────

    def _validate_sub_agent_tools(self, agent_name: str, allowed: list[str]) -> None:
        """Ensure a sub-agent's tools don't exceed its privilege level.

        Raises ValueError if the sub-agent has tools it shouldn't.
        """
        for tool_name in allowed:
            if not is_tool_allowed(tool_name):
                raise ValueError(
                    f"Sub-agent '{agent_name}' uses unknown tool '{tool_name}'"
                )

    def _check_tool_approval(self, agent_name: str, tool_name: str, args: dict) -> ApprovalRequest | None:
        """Check if a tool call needs approval. Returns ApprovalRequest if so."""
        risk = get_tool_risk(tool_name)
        if needs_approval(tool_name, self.auto_approve_risk):
            req = ApprovalRequest(
                id=f"apr-{len(self.approvals)+1:04d}",
                tool_name=tool_name,
                arguments=args,
                risk_level=risk,
                reason=f"Sub-agent '{agent_name}' wants to use '{tool_name}'",
            )
            self.approvals.append(req)
            log_event(
                event_type="approval_required",
                agent=agent_name,
                tool_name=tool_name,
                risk_level=risk.value,
                parameters=args,
            )
            return req
        return None

    # ── Main execution ─────────────────────────────────────

    async def run(self, task: str) -> OrchestratorResult:
        """Execute the full multi-agent workflow."""
        start = time.perf_counter()
        result = OrchestratorResult(task=task, success=True)

        logger.info("ORCHESTRATOR | starting task: %s...", task[:100])

        # ── Retrieve long-term memory for context ────────────
        memory_context = ""
        try:
            from app.memory.long_term import search_memories

            fix_results = await search_memories(task, "fix_patterns", n_results=2)
            convention_results = await search_memories(task, "project_conventions", n_results=2)
            pref_results = await search_memories(task, "user_preferences", n_results=1)

            parts = []
            if fix_results:
                parts.append("Similar past fixes:\n" + "\n".join(f"- {r['content'][:250]}" for r in fix_results))
            if convention_results:
                parts.append("Project conventions:\n" + "\n".join(f"- {r['content'][:250]}" for r in convention_results))
            if pref_results:
                parts.append("User preferences:\n" + "\n".join(f"- {r['content'][:250]}" for r in pref_results))
            if parts:
                memory_context = "\n\nRelevant past experience:\n" + "\n".join(parts)
                logger.info("ORCHESTRATOR | injected memory: %d fix + %d convention + %d pref",
                             len(fix_results), len(convention_results), len(pref_results))
        except Exception as exc:
            logger.debug("ORCHESTRATOR | memory search skipped: %s", exc)

        # Augment task with memory context for sub-agents
        augmented_task = task + memory_context

        try:
            # Phase 1: ANALYZE
            result.phases.append({"phase": "analyze", "status": "running"})
            analyst_result = await self.analyst.run(augmented_task)
            result.analyst_result = analyst_result
            result.phases[-1]["status"] = "completed"
            result.phases[-1]["output"] = analyst_result.output[:500]
            log_event(
                event_type="phase_complete",
                agent="orchestrator",
                extra={"phase": "analyze", "duration_ms": analyst_result.duration_ms},
            )
            logger.info("ORCHESTRATOR | analyze complete (%d ms)", analyst_result.duration_ms)

            # Phase 2: IMPLEMENT
            result.phases.append({"phase": "implement", "status": "running"})
            implementer_result = await self.implementer.run(augmented_task)
            result.implementer_result = implementer_result
            result.phases[-1]["status"] = "completed"
            result.phases[-1]["output"] = implementer_result.output[:500]

            # Check for write_patch approval needs
            for tc in implementer_result.tool_calls:
                tool_name = tc.get("tool", "")
                if tool_name == "write_patch":
                    self._check_tool_approval("Implementer", tool_name, tc.get("data", {}))

            log_event(
                event_type="phase_complete",
                agent="orchestrator",
                extra={"phase": "implement", "duration_ms": implementer_result.duration_ms},
            )
            logger.info("ORCHESTRATOR | implement complete (%d ms)", implementer_result.duration_ms)

            # Phase 3: REVIEW
            result.phases.append({"phase": "review", "status": "running"})
            reviewer_result = await self.reviewer.run(augmented_task)
            result.reviewer_result = reviewer_result
            result.phases[-1]["status"] = "completed"
            result.phases[-1]["output"] = reviewer_result.output[:500]

            # Check for run_tests approval needs
            for tc in reviewer_result.tool_calls:
                tool_name = tc.get("tool", "")
                if tool_name == "run_tests":
                    self._check_tool_approval("Reviewer", tool_name, tc.get("data", {}))

            log_event(
                event_type="phase_complete",
                agent="orchestrator",
                extra={"phase": "review", "duration_ms": reviewer_result.duration_ms},
            )
            logger.info("ORCHESTRATOR | review complete (%d ms)", reviewer_result.duration_ms)

            # Phase 4: DONE — synthesize
            result.phases.append({"phase": "done", "status": "completed"})
            result.final_summary = self._synthesize(task, result)
            result.success = True

            # Persist insights to long-term memory
            try:
                from app.memory.long_term import extract_and_store_insights
                await extract_and_store_insights(
                    task=task,
                    final_summary=result.final_summary,
                    files_involved=None,  # Could extract from tool results
                )
            except Exception as mem_exc:
                logger.warning("Failed to store long-term memory: %s", mem_exc)

        except Exception as exc:
            logger.exception("ORCHESTRATOR | error: %s", exc)
            result.success = False
            result.error = str(exc)
            result.final_summary = f"Error during orchestration: {exc}"

        result.total_duration_ms = (time.perf_counter() - start) * 1000
        result.approvals = self.approvals

        log_event(
            event_type="orchestrator_complete",
            agent="orchestrator",
            success=result.success,
            duration_ms=result.total_duration_ms,
            extra={"phases": len(result.phases), "approvals": len(self.approvals)},
        )

        return result

    def _synthesize(self, task: str, result: OrchestratorResult) -> str:
        """Combine sub-agent outputs into a final summary."""
        parts = [
            f"# CodeSentry Report",
            f"",
            f"## Task",
            f"{task}",
            f"",
            f"## Repository Analysis",
        ]

        if result.analyst_result:
            parts.append(result.analyst_result.output[:800])

        parts.extend(["", "## Implementation"])

        if result.implementer_result:
            parts.append(result.implementer_result.output[:800])

        parts.extend(["", "## Review & Tests"])

        if result.reviewer_result:
            parts.append(result.reviewer_result.output[:800])

        if self.approvals:
            parts.extend(["", "## Pending Approvals"])
            for apr in self.approvals:
                parts.append(
                    f"- [{apr.risk_level.value.upper()}] `{apr.tool_name}` — {apr.reason} "
                    f"(status: {apr.status.value})"
                )

        parts.extend([
            "",
            "## Summary",
            f"- Phases completed: {sum(1 for p in result.phases if p['status']=='completed')}/{len(result.phases)}",
            f"- Total approvals required: {len(self.approvals)}",
            f"- Total duration: {result.total_duration_ms:.0f}ms",
        ])

        return "\n".join(parts)
