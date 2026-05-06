"""Implementer — restricted write sub-agent for code modifications.

Uses LLM with tool calling to understand code and propose changes.
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
            "- write_patch：将新内容写入文件（会先创建备份）。这是唯一修改文件的方式。\n\n"
            "规则：\n"
            "1. 先用 read_file 理解需要变更的文件。\n"
            "2. 思考需要什么变更，先用中文解释你的方案。\n"
            "3. 用 write_patch 逐个应用变更。提供完整的文件新内容，不要只给 diff。\n"
            "4. 精准修改——只改完成任务必需的部分。\n"
            "5. 修改完成后用中文总结你改了什么以及为什么。\n"
            "6. 如果任务是只读的（只是查询信息），说明无需修改并提供相关信息。\n\n"
            "⚠️ 注意：write_patch 需要编排器批准后才会真正生效。"
        )

    async def run(self, task_context: str) -> SubAgentResult:
        """Propose and (with approval) implement changes via LLM."""
        import time

        start = time.perf_counter()

        try:
            output, tool_calls = await self._llm_call(task_context)
            success = True
        except Exception:
            output = f"[{self.name}] Implementation failed — see logs for details."
            tool_calls = []
            success = False

        duration = (time.perf_counter() - start) * 1000

        return SubAgentResult(
            agent_name=self.name,
            success=success,
            output=output,
            tool_calls=tool_calls,
            duration_ms=duration,
        )
