"""Reviewer / Test Agent — validates changes and runs tests.

Uses LLM with tool calling to review diffs and execute tests.
Test execution goes through the Orchestrator's approval gate.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.base_agent import BaseSubAgent, SubAgentResult
from app.tools.base import ToolResult

logger = logging.getLogger(__name__)


class Reviewer(BaseSubAgent):
    """Read + test-execution agent that validates code changes.

    Allowed tools:
      - read_file: review changed code
      - run_tests: execute test suite (REQUIRES Orchestrator approval)
      - git_diff: inspect the diff of changes

    The Reviewer CANNOT directly execute run_tests — it must go through
    the Orchestrator's approval flow.
    """

    name = "代码审查者"
    description = "审查代码变更的正确性、风格和安全性，运行测试验证。测试执行需经编排器批准。"
    allowed_tools = ["read_file", "run_tests", "git_diff"]

    @property
    def system_prompt(self) -> str:
        return (
            "你是 CodeSentry 的代码审查者子智能体。"
            "你的任务是审查代码变更并运行测试验证一切正常。\n\n"
            "可用工具：\n"
            "- git_diff：查看文件变更和差异内容。\n"
            "- read_file：读取文件内容进行详细审查。\n"
            "- run_tests：执行测试命令（例如 'pytest'、'python -m pytest tests/'），需要编排器批准。\n\n"
            "规则（严格遵守）：\n"
            "1. 始终先用 git_diff 查看变更。\n"
            "2. 如果 git_diff 为空（没有任何变更）：立即停止并报告「无代码变更——此任务为只读，无需测试。」不要调用任何其他工具。\n"
            "3. 仅当有实际变更时：用 read_file 审查变更内容，然后调用 run_tests 一次（使用合适的命令如 'pytest' 或 'python -m pytest tests/'）。\n"
            "4. 同一工具调用失败后绝不重试——报告失败即可。\n"
            "5. 用中文简洁报告：变更内容、测试结果、发现的问题。"
        )

    async def _rule_based_run(self, task_context: str) -> tuple[str, list[dict[str, Any]]]:
        """Deterministic review fallback when the LLM is unavailable.

        Checks the diff, then runs the project test suite (approval-gated).
        """
        results: list[dict[str, Any]] = []

        async def _tool(name: str, **kwargs: Any) -> ToolResult:
            try:
                return await self._execute_tool_with_approval(name, kwargs)
            except Exception as exc:
                return ToolResult(tool_name=name, success=False, error=str(exc))

        gd = await _tool("git_diff")
        results.append(gd.to_dict())
        has_changes = gd.success and not (gd.data or {}).get("empty", True)

        rt = await _tool("run_tests", command="python -m pytest", timeout_seconds=60)
        results.append(rt.to_dict())

        if rt.success and isinstance(rt.data, dict):
            test_line = f"- run_tests: 'python -m pytest' exit={rt.data.get('exit_code')}"
        else:
            test_line = f"- run_tests: failed ({rt.error or 'unknown error'})"

        lines = [
            f"[{self.name}] No LLM configured — rule-based review:",
            "",
            f"- git_diff: {'uncommitted changes present' if has_changes else 'no diff / not a git repo'}",
            test_line,
            "",
            "ORCHESTRATOR APPROVAL REQUIRED for any run_tests.",
        ]
        return "\n".join(lines), results

    async def run(self, task_context: str) -> SubAgentResult:
        """Review changes and run tests via LLM."""
        import time

        start = time.perf_counter()

        try:
            output, tool_calls = await self._llm_call(task_context, max_rounds=4)
            if output.startswith(f"[{self.name}] LLM call"):
                raise RuntimeError(output)
            success = True
        except Exception as exc:
            logger.warning(
                "%s | LLM unavailable (%s) — using rule-based review",
                self.name, exc,
            )
            try:
                output, tool_calls = await self._rule_based_run(task_context)
            except Exception as fallback_exc:
                logger.exception("%s | rule-based review failed", self.name)
                output = f"[{self.name}] Review failed: {fallback_exc}"
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
