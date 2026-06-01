"""Repository Analyst — read-only sub-agent for code exploration.

Uses LLM with tool calling to dynamically explore the repository
based on the task at hand.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.base_agent import BaseSubAgent, SubAgentResult
from app.tools.base import ToolResult

logger = logging.getLogger(__name__)


def _render_file_tree(
    file_paths: list[str],
    max_depth: int = 4,
    max_per_dir: int = 20,
    max_lines: int = 50,
) -> list[str]:
    """Render a compact directory tree from flat file paths."""
    root: dict[str, Any] = {}
    for p in file_paths:
        parts = [x for x in p.replace("\\", "/").split("/") if x]
        node = root
        for part in parts:
            node = node.setdefault(part, {})

    out: list[str] = []

    def walk(node: dict[str, Any], prefix: str, depth: int) -> None:
        if depth >= max_depth or len(out) >= max_lines:
            return
        items = sorted(node.items(), key=lambda kv: (not kv[1], kv[0].lower()))
        dirs = [(k, v) for k, v in items if v]
        files = [(k, v) for k, v in items if not v]
        total = dirs + files
        shown = total[:max_per_dir]
        hidden = len(total) - len(shown)
        for i, (name, children) in enumerate(shown):
            if len(out) >= max_lines:
                return
            is_last = i == len(shown) - 1 and hidden == 0
            connector = "└── " if is_last else "├── "
            if children:
                out.append(f"{prefix}{connector}{name}/")
                child_prefix = prefix + ("    " if is_last else "│   ")
                walk(children, child_prefix, depth + 1)
            else:
                out.append(f"{prefix}{connector}{name}")
        if hidden:
            out.append(f"{prefix}└── … 还有 {hidden} 项")

    walk(root, "", 0)
    return out or ["(empty workspace)"]


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
            "1. 先用 list_files 了解顶层结构。注意：list_files 默认只列一层，"
            "你必须继续对主要子目录（如 backend/、frontend/、src/）再次调用 list_files 深入，"
            "直到看清整体结构，至少深入两层。\n"
            "2. 用 search_code 定位关键代码：类/函数定义、TODO、依赖等。\n"
            "3. 用 read_file 至少阅读 3 个关键文件（入口文件、配置、核心模块）"
            "取得具体内容，不要只看目录名就下结论。\n"
            "4. 你有多轮工具调用机会：上一轮工具结果返回后，若信息不足就继续调用工具，"
            "信息足够再给出结论。禁止只列一次目录就写总结。\n"
            "5. 报告中的「项目结构」必须用代码块里的树形图呈现（用 ├── / └── / │ 缩进），"
            "目录在前文件在后，每个目录最多列 15 项，总行数不超过 40 行，"
            "被截断的目录写一行「… 还有 N 项」。禁止把文件列成一长串扁平列表。\n"
            "6. 结论必须具体：引用真实文件名、函数名、代码行为依据。"
            "没有文件依据的内容不得编造，没有深入调查的部分要明确说明「未深入」。\n"
            "7. 收集足够信息后，用中文提供清晰、结构化的发现总结。\n"
            "8. 不要修改或建议修改代码——你只负责分析。"
        )

    async def _rule_based_run(self, task_context: str) -> tuple[str, list[dict[str, Any]]]:
        """Deterministic exploration fallback when the LLM is unavailable."""
        results: list[dict[str, Any]] = []

        async def _tool(name: str, **kwargs: Any) -> ToolResult:
            try:
                return await self._execute_tool_with_approval(name, kwargs)
            except Exception as exc:
                return ToolResult(tool_name=name, success=False, error=str(exc))

        lines: list[str] = ["## Repository structure", ""]
        file_paths: list[str] = []

        ls = await _tool("list_files", path=".", recursive=True)
        results.append(ls.to_dict())
        if ls.success:
            entries = (ls.data or {}).get("entries", []) or []
            file_paths = [e["path"] for e in entries if e.get("type") == "file"]
            if file_paths:
                lines.append("```")
                lines.extend(_render_file_tree(file_paths))
                lines.append("```")
            else:
                lines.append("- (empty workspace)")
        else:
            lines.append(f"- listing failed: {ls.error}")

        py_files = [p for p in file_paths if p.endswith(".py")]
        lines.append("")
        lines.append(f"Total files: {len(file_paths)} | Python files: {len(py_files)}")

        # Keyword-driven search for likely problems / targets.
        task_lower = task_context.lower()
        if any(
            k in task_lower
            for k in ("todo", "fixme", "fix", "bug", "issue", "broken", "error")
        ):
            sc = await _tool(
                "search_code", pattern="TODO|FIXME|bug|error", path=".", max_results=10
            )
            results.append(sc.to_dict())
            if sc.success:
                matches = (sc.data or {}).get("results", []) or []
                lines.append("")
                if matches:
                    lines.append("## Findings (TODO/FIXME/bug markers)")
                    for m in matches[:10]:
                        lines.append(f"- {m['file']}:{m['line']} {m['content'][:100]}")
                else:
                    lines.append("## Findings\nNo TODO/FIXME/bug markers found.")

        gd = await _tool("git_diff")
        results.append(gd.to_dict())
        lines.append("")
        lines.append("## VCS state")
        if gd.success and not (gd.data or {}).get("empty", True):
            lines.append("- There are uncommitted changes in the workspace.")
        else:
            lines.append("- No uncommitted changes (or not a git repo).")

        output = f"[{self.name}] No LLM configured — rule-based exploration:\n\n" + "\n".join(lines)
        return output, results

    async def run(self, task_context: str) -> SubAgentResult:
        """Explore the repo using LLM-driven tool calling."""
        import time

        start = time.perf_counter()

        try:
            output, tool_calls = await self._llm_call(task_context)
            if output.startswith(f"[{self.name}] LLM call"):
                # LLM genuinely unavailable (timeout/network) — degrade to the
                # deterministic exploration instead of reporting garbage.
                raise RuntimeError(output)
            success = True
        except Exception as exc:
            logger.warning(
                "%s | LLM unavailable (%s) — using rule-based exploration",
                self.name, exc,
            )
            try:
                output, tool_calls = await self._rule_based_run(task_context)
            except Exception as fallback_exc:
                logger.exception("%s | rule-based exploration failed", self.name)
                output = f"[{self.name}] Exploration failed: {fallback_exc}"
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
