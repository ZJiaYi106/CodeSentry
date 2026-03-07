"""Tool registry — creates and manages all tool instances."""

from __future__ import annotations

from typing import Any

from app.tools.base import BaseTool
from app.tools.code_search import SearchCodeTool
from app.tools.file_list import ListFilesTool
from app.tools.git_diff import GitDiffTool
from app.tools.read_file import ReadFileTool
from app.tools.run_tests import RunTestsTool
from app.tools.write_patch import WritePatchTool


class ToolRegistry:
    """Manages tool instances and provides lookup by name."""

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self._tools: dict[str, BaseTool] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register all six built-in tools."""
        for cls in [
            ListFilesTool,
            SearchCodeTool,
            ReadFileTool,
            WritePatchTool,
            RunTestsTool,
            GitDiffTool,
        ]:
            tool = cls(workspace_root=self.workspace_root)
            self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        """Return a tool by name. Raises KeyError if not found."""
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not found in registry.")
        return self._tools[name]

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def to_openai_functions(self) -> list[dict[str, Any]]:
        """Return OpenAI function-calling definitions for all tools."""
        return [t.to_openai_function() for t in self._tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self._tools
