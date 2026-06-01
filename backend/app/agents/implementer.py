"""Implementer — restricted write sub-agent for code modifications.

Uses LLM with tool calling to understand code and propose changes.
ALL writes go through the Orchestrator's approval gate.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.agents.base_agent import BaseSubAgent, SubAgentResult
from app.tools.base import ToolResult

logger = logging.getLogger(__name__)

# File-like tokens we can spot in a task description for the rule-based fallback.
_FILE_RE = re.compile(
    r"([A-Za-z0-9_.\-/\\]+\.(?:py|js|ts|tsx|jsx|go|rs|java|c|cc|cpp|h|hpp|rb|php"
    r"|json|yaml|yml|toml|md|txt|cfg|ini|env))"
)


class Implementer(BaseSubAgent):
    """Restricted agent that proposes and (with approval) applies code changes.

    Allowed tools:
      - read_file: understand the code to modify
      - write_patch: propose/modify files (REQUIRES Orchestrator approval)

    The Implementer CANNOT directly execute write_patch — it must go through
    the Orchestrator's approval flow.
    """

    name = "代码实现者"
    description = "根据任务需求和仓库分析师的分析结果实现代码变更，所有写入操作需经编排器批准。"
    allowed_tools = ["read_file", "write_patch"]

    @property
    def system_prompt(self) -> str:
        return (
            "你是 CodeSentry 的代码实现者子智能体。"
            "你的任务是根据用户需求进行代码修改。\n\n"
            "可用工具：\n"
            "- read_file：读取文件内容。先用它理解需要修改的代码。\n"
            "- write_patch：将新内容写入文件。若目标文件已存在，改动会写入新文件「原名.new.扩展名」（如 a.cpp → a.new.cpp），"
            "原文件保持不变；若文件不存在则直接创建。这是唯一修改文件的方式。\n\n"
            "规则：\n"
            "1. 先用 read_file 理解需要变更的文件。\n"
            "2. 思考需要什么变更，先用中文解释你的方案。\n"
            "3. 用 write_patch 逐个应用变更。提供完整的文件新内容，不要只给 diff。\n"
            "4. 精准修改——只改完成任务必需的部分。\n"
            "5. 修改完成后用中文总结你改了什么以及为什么。\n"
            "6. 如果任务是只读的（只是查询信息），说明无需修改并提供相关信息。\n\n"
            "⚠️ 注意：write_patch 需要编排器批准后才会真正生效。"
        )

    async def _rule_based_run(self, task_context: str) -> tuple[str, list[dict[str, Any]]]:
        """Deterministic proposal fallback when the LLM is unavailable.

        Only reads files and describes what would change — never writes,
        because there is no LLM to verify the edit is correct.
        """
        results: list[dict[str, Any]] = []

        async def _tool(name: str, **kwargs: Any) -> ToolResult:
            try:
                return await self._execute_tool_with_approval(name, kwargs)
            except Exception as exc:
                return ToolResult(tool_name=name, success=False, error=str(exc))

        seen = list(dict.fromkeys(m for m in _FILE_RE.findall(task_context)))

        lines = [
            f"[{self.name}] No LLM configured — rule-based proposal (no changes applied):",
            "",
            "## Proposed Changes",
            "",
        ]

        if seen:
            for f in seen:
                rd = await _tool("read_file", file_path=f, limit=50)
                results.append(rd.to_dict())
                if rd.success:
                    content = (rd.data or {}).get("content", "")
                    lines.append(
                        f"- Would modify `{f}` ({len(content.splitlines())} lines read)"
                    )
                else:
                    lines.append(f"- `{f}` could not be read: {rd.error}")
            lines.append("")
            lines.append("(LLM unavailable — patch generation skipped; nothing was written.)")
        else:
            lines.append("- No specific file identified from the task text.")
            lines.append("")

        lines.extend([
            "",
            "## Approval",
            "",
            "ORCHESTRATOR APPROVAL REQUIRED for any write_patch.",
        ])
        return "\n".join(lines), results

    async def run(self, task_context: str) -> SubAgentResult:
        """Propose and (with approval) implement changes via LLM."""
        import time

        start = time.perf_counter()

        try:
            output, tool_calls = await self._llm_call(task_context)
            if output.startswith(f"[{self.name}] LLM call"):
                raise RuntimeError(output)
            success = True
        except Exception as exc:
            logger.warning(
                "%s | LLM unavailable (%s) — using rule-based proposal",
                self.name, exc,
            )
            try:
                output, tool_calls = await self._rule_based_run(task_context)
            except Exception as fallback_exc:
                logger.exception("%s | rule-based proposal failed", self.name)
                output = f"[{self.name}] Proposal failed: {fallback_exc}"
                tool_calls = []
            success = True

        duration = (time.perf_counter() - start) * 1000

        return SubAgentResult(
            agent_name=self.name,
            success=success,
            output=output,
            tool_calls=tool_calls,
            duration_ms=duration,
        )
