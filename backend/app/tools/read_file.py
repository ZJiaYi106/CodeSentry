"""Read file contents within the workspace."""

from __future__ import annotations

import os
from typing import Any

from app.tools.base import BaseTool, RiskLevel, ToolParameter, ToolResult


class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "Read the contents of a file within the workspace. "
        "Supports line offsets and limits for large files."
    )
    risk_level = RiskLevel.LOW
    parameters = [
        ToolParameter(name="file_path", description="Path to the file, relative to workspace root"),
        ToolParameter(name="offset", type="integer", description="Line number to start reading from (1-indexed)", required=False, default=1),
        ToolParameter(name="limit", type="integer", description="Max lines to read", required=False, default=200),
    ]

    async def execute(self, **kwargs: Any) -> ToolResult:
        # file_path already resolved by base.run()
        full_path: str = kwargs.get("file_path", "")
        offset: int = int(kwargs.get("offset", 1))
        limit: int = int(kwargs.get("limit", 200))

        if not os.path.exists(full_path):
            return ToolResult(tool_name=self.name, success=False, error=f"File not found: {full_path}")
        if os.path.isdir(full_path):
            return ToolResult(tool_name=self.name, success=False, error=f"Path is a directory: {full_path}")
        try:
            if os.path.getsize(full_path) > 2_000_000:
                return ToolResult(tool_name=self.name, success=False, error=f"File too large (>2MB): {full_path}")
        except OSError as exc:
            return ToolResult(tool_name=self.name, success=False, error=str(exc))

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as fh:
                all_lines = fh.readlines()
        except (OSError, PermissionError) as exc:
            return ToolResult(tool_name=self.name, success=False, error=str(exc))

        total_lines = len(all_lines)
        start = max(0, offset - 1)
        end = min(start + limit, total_lines)
        selected = all_lines[start:end]

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "file": os.path.relpath(full_path, self.workspace_root),
                "total_lines": total_lines,
                "offset": offset,
                "limit": limit,
                "lines_returned": len(selected),
                "content": "".join(selected),
            },
        )
