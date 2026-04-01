"""Implementer — restricted write sub-agent for code modifications.

ALL writes go through the Orchestrator's approval gate.
"""

from __future__ import annotations

from app.agents.base_agent import BaseSubAgent, SubAgentResult


class Implementer(BaseSubAgent):
    """Restricted agent that proposes and (with approval) applies code changes.

    Allowed tools:
      - read_file: understand the code to modify
      - write_patch: propose/modify files (REQUIRES Orchestrator approval)

    The Implementer CANNOT directly execute write_patch — it must go through
    the Orchestrator's approval flow.  In the fallback mode, it describes
    what changes it WOULD make.
    """

    name = "Implementer"
    description = (
        "I implement code changes based on the task requirements and "
        "the analysis provided by the Repository Analyst. "
        "All my writes must be approved by the Orchestrator."
    )
    allowed_tools = ["read_file", "write_patch"]

    async def run(self, task_context: str) -> SubAgentResult:
        """Propose and (with approval) implement changes."""
        import time

        start = time.perf_counter()

        lines: list[str] = []
        tool_calls: list[dict] = []

        # The Implementer first reads relevant files to understand context,
        # then proposes changes.  Write operations are gated by the Orchestrator.

        # Extract potential file paths from the task context
        import re
        file_pattern = re.compile(r'["\']?([\w./-]+\.(?:py|js|ts|tsx|jsx|go|rs|java))["\']?')
        mentioned_files = file_pattern.findall(task_context)

        # Read mentioned files to gather context
        for fpath in mentioned_files[:3]:  # Max 3 files
            try:
                reader = self._registry.get("read_file")
                result = await reader.run(file_path=fpath, limit=50)
                tool_calls.append(result.to_dict())
                if result.success:
                    lines.append(f"Read {fpath}: {result.data.get('total_lines', '?')} lines")
                    lines.append(f"  Content preview: {result.data.get('content', '')[:200]}")
            except Exception as exc:
                lines.append(f"Could not read {fpath}: {exc}")

        # Describe proposed changes (in full impl this would be LLM-generated)
        lines.append("")
        lines.append("## Proposed Changes")
        lines.append(f"Task: {task_context[:300]}")
        lines.append("")
        lines.append("The Implementer would:")
        lines.append("1. Read the target files to understand current implementation")
        lines.append("2. Generate a unified diff patch with the proposed changes")
        lines.append("3. Submit the patch for Orchestrator approval")
        lines.append("4. Apply the patch only after approval is granted")
        lines.append("")
        lines.append("⚠️  WRITE OPERATIONS REQUIRE ORCHESTRATOR APPROVAL ⚠️")

        duration = (time.perf_counter() - start) * 1000
        return SubAgentResult(
            agent_name=self.name,
            success=True,
            output="\n".join(lines),
            tool_calls=tool_calls,
            duration_ms=duration,
        )
