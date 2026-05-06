"""Repository Analyst — read-only sub-agent for code exploration.

Uses LLM with tool calling to dynamically explore the repository
based on the task at hand.
"""

from __future__ import annotations

from app.agents.base_agent import BaseSubAgent, SubAgentResult


class RepoAnalyst(BaseSubAgent):
    """Read-only agent that explores the repository structure and code.

    Allowed tools (read-only, low risk):
      - list_files: discover project structure
      - search_code: find relevant code patterns
      - read_file: understand implementation details
      - git_diff: see current changes
    """

    name = "仓库分析师"
    description = "探索代码仓库结构，识别相关文件，收集任务所需的上下文。"
    allowed_tools = ["list_files", "search_code", "read_file", "git_diff"]

    @property
    def system_prompt(self) -> str:
        return (
            "你是 CodeSentry 的仓库分析师子智能体。"
            "你的任务是探索代码库，收集完成用户任务所需的所有相关信息。\n\n"
            "可用工具：\n"
            "- list_files：列出目录中的文件和文件夹。首先使用此工具了解项目结构。\n"
            "- search_code：在代码文件中搜索正则表达式。用于查找相关函数、类或模式。\n"
            "- read_file：读取指定文件的内容。用于检查通过 list_files 或 search_code 找到的文件。\n"
            "- git_diff：查看仓库中当前未提交的变更。\n\n"
            "规则：\n"
            "1. 先用 list_files 了解整体结构。\n"
            "2. 用 search_code 定位相关代码。\n"
            "3. 用 read_file 获取关键文件的完整上下文。\n"
            "4. 要全面但聚焦——只读取与任务相关的文件。\n"
            "5. 收集足够信息后，用中文提供清晰、结构化的发现总结，包含文件路径和相关代码摘要。\n"
            "6. 不要修改或建议修改代码——你只负责分析。"
        )

    async def run(self, task_context: str) -> SubAgentResult:
        """Explore the repo using LLM-driven tool calling."""
        import time

        start = time.perf_counter()

        try:
            output, tool_calls = await self._llm_call(task_context)
            success = True
        except Exception:
            output = f"[{self.name}] Analysis failed — see logs for details."
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
