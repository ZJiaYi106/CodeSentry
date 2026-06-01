"""Controlled file write / patch application tool.

HIGH risk — modifies files.  All calls must be approved.

Behavior:
  - Target file does NOT exist → the new content is written directly to it.
  - Target file EXISTS → the original is left untouched and the new content
    is written to a sibling file named '<name>.new.<ext>' (e.g. a.cpp →
    a.new.cpp). This keeps the original as an implicit backup and makes
    AI-proposed changes easy to review before adopting them.
"""

from __future__ import annotations

import os
from typing import Any

from app.tools.base import BaseTool, RiskLevel, ToolParameter, ToolResult


class WritePatchTool(BaseTool):
    name = "write_patch"
    description = (
        "Write or modify a file within the workspace. "
        "If the target file already exists, the new content is written to a NEW "
        "sibling file named '<name>.new.<ext>' (e.g. a.cpp -> a.new.cpp) and the "
        "original file is left untouched. If the file does not exist yet, it is "
        "created directly at the given path."
    )
    risk_level = RiskLevel.HIGH
    parameters = [
        ToolParameter(name="file_path", description="Path to the file to write, relative to workspace root"),
        ToolParameter(name="content", description="New file content to write"),
    ]

    async def execute(self, **kwargs: Any) -> ToolResult:
        # file_path already resolved by base.run()
        full_path: str = kwargs.get("file_path", "")
        content: str = kwargs.get("content", "")

        # Ensure parent directory exists
        parent = os.path.dirname(full_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

        existed = os.path.exists(full_path)

        # Existing files are never overwritten: the modified version goes to
        # a new sibling file, keeping the original as an implicit backup.
        if existed:
            dir_name, base = os.path.split(full_path)
            stem, ext = os.path.splitext(base)
            variant_path = os.path.join(dir_name, f"{stem}.new{ext}")
        else:
            variant_path = full_path

        try:
            with open(variant_path, "w", encoding="utf-8") as fh:
                fh.write(content)
        except (OSError, PermissionError) as exc:
            return ToolResult(tool_name=self.name, success=False, error=f"Write failed: {exc}")

        file_size = os.path.getsize(variant_path)
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "file": os.path.relpath(variant_path, self.workspace_root),
                "original_file": os.path.relpath(full_path, self.workspace_root) if existed else None,
                "existed_before": existed,
                "created_new_variant": existed,
                "original_untouched": existed,
                "size_bytes": file_size,
                "lines_written": content.count("\n") + (0 if content.endswith("\n") else 1),
            },
        )
