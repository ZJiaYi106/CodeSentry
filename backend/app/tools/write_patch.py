"""Controlled file write / patch application tool.

HIGH risk — modifies files.  All calls must be approved.
"""

from __future__ import annotations

import os
from typing import Any

from app.tools.base import BaseTool, RiskLevel, ToolParameter, ToolResult


class WritePatchTool(BaseTool):
    name = "write_patch"
    description = (
        "Write or modify a file within the workspace. "
        "Provide the relative file path and the new content. "
        "A backup of the original file is created before modification."
    )
    risk_level = RiskLevel.HIGH
    parameters = [
        ToolParameter(name="file_path", description="Path to the file to write, relative to workspace root"),
        ToolParameter(name="content", description="New file content to write"),
        ToolParameter(name="create_backup", type="boolean", description="Create a .bak backup before writing (default: true)", required=False, default=True),
    ]

    async def execute(self, **kwargs: Any) -> ToolResult:
        # file_path already resolved by base.run()
        full_path: str = kwargs.get("file_path", "")
        content: str = kwargs.get("content", "")
        create_backup: bool = bool(kwargs.get("create_backup", True))

        # Ensure parent directory exists
        parent = os.path.dirname(full_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

        existed = os.path.exists(full_path)

        # Backup original
        if existed and create_backup:
            backup_path = full_path + ".bak"
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as src:
                    original = src.read()
                with open(backup_path, "w", encoding="utf-8") as dst:
                    dst.write(original)
            except (OSError, PermissionError) as exc:
                return ToolResult(tool_name=self.name, success=False, error=f"Backup failed: {exc}")

        # Write
        try:
            with open(full_path, "w", encoding="utf-8") as fh:
                fh.write(content)
        except (OSError, PermissionError) as exc:
            return ToolResult(tool_name=self.name, success=False, error=f"Write failed: {exc}")

        file_size = os.path.getsize(full_path)
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "file": os.path.relpath(full_path, self.workspace_root),
                "existed_before": existed,
                "backup_created": existed and create_backup,
                "size_bytes": file_size,
                "lines_written": content.count("\n") + (0 if content.endswith("\n") else 1),
            },
        )
