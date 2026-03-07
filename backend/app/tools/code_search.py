"""Search code within workspace files using regex patterns."""

from __future__ import annotations

import fnmatch
import os
import re
from typing import Any

from app.tools.base import BaseTool, RiskLevel, ToolParameter, ToolResult

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".c", ".cpp",
    ".h", ".hpp", ".rb", ".php", ".swift", ".kt", ".scala", ".cs", ".fs",
    ".vue", ".svelte", ".html", ".css", ".scss", ".less", ".json", ".yaml",
    ".yml", ".toml", ".xml", ".md", ".rst", ".txt", ".sh", ".bash", ".zsh",
    ".sql", ".graphql", ".proto", ".tf", ".dockerfile", ".env", ".cfg", ".ini",
}


class SearchCodeTool(BaseTool):
    name = "search_code"
    description = (
        "Search for a regex pattern across all code files in a directory. "
        "Returns matching file paths and line content."
    )
    risk_level = RiskLevel.LOW
    parameters = [
        ToolParameter(name="pattern", description="Regex pattern to search for"),
        ToolParameter(name="path", description="Directory to search (defaults to workspace root)", required=False, default="."),
        ToolParameter(name="file_pattern", description="Optional glob to filter files (e.g. '*.py')", required=False),
        ToolParameter(name="max_results", type="integer", description="Maximum results to return", required=False, default=50),
    ]

    async def execute(self, **kwargs: Any) -> ToolResult:
        pattern: str = kwargs.get("pattern", "")
        # Path already resolved by base.run()
        full_path: str = kwargs.get("path", self.workspace_root)
        file_pattern: str | None = kwargs.get("file_pattern")
        max_results: int = int(kwargs.get("max_results", 50))

        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            return ToolResult(tool_name=self.name, success=False, error=f"Invalid regex: {exc}")

        results: list[dict[str, Any]] = []
        searched = 0

        for root, dirs, files in os.walk(full_path):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            rel_root = os.path.relpath(root, self.workspace_root)

            for fname in sorted(files):
                if fname.startswith("."):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    if os.path.getsize(fpath) > 1_000_000:
                        continue
                except OSError:
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in CODE_EXTENSIONS:
                    continue
                if file_pattern and not fnmatch.fnmatch(fname, file_pattern):
                    continue

                searched += 1
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                        for lineno, line in enumerate(fh, 1):
                            if compiled.search(line):
                                results.append({
                                    "file": os.path.join(rel_root, fname),
                                    "line": lineno,
                                    "content": line.rstrip()[:200],
                                })
                                if len(results) >= max_results:
                                    break
                except (OSError, PermissionError):
                    continue

                if len(results) >= max_results:
                    break

            if len(results) >= max_results:
                break

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "pattern": pattern,
                "files_searched": searched,
                "match_count": len(results),
                "truncated": len(results) >= max_results,
                "results": results,
            },
        )
