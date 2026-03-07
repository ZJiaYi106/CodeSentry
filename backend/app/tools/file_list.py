"""List files in a directory within the workspace."""

from __future__ import annotations

import os
from typing import Any

from app.tools.base import BaseTool, RiskLevel, ToolParameter, ToolResult


class ListFilesTool(BaseTool):
    name = "list_files"
    description = "List files and directories at a given path within the workspace."
    risk_level = RiskLevel.LOW
    parameters = [
        ToolParameter(name="path", description="Directory path relative to workspace root", required=False, default="."),
        ToolParameter(name="recursive", type="boolean", description="Whether to list recursively", required=False, default=False),
    ]

    async def execute(self, **kwargs: Any) -> ToolResult:
        # Path already resolved by base.run() — use directly
        full_path: str = kwargs.get("path", self.workspace_root)
        recursive: bool = bool(kwargs.get("recursive", False))

        if not os.path.exists(full_path):
            return ToolResult(tool_name=self.name, success=False, error=f"Path not found: {full_path}")
        if not os.path.isdir(full_path):
            return ToolResult(tool_name=self.name, success=False, error=f"Not a directory: {full_path}")

        entries: list[dict[str, Any]] = []
        if recursive:
            for root, dirs, files in os.walk(full_path):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                rel_root = os.path.relpath(root, self.workspace_root)
                for name in sorted(dirs):
                    entries.append({"type": "dir", "path": os.path.join(rel_root, name)})
                for name in sorted(files):
                    if name.startswith("."):
                        continue
                    entries.append({"type": "file", "path": os.path.join(rel_root, name)})
        else:
            with os.scandir(full_path) as it:
                for entry in sorted(it, key=lambda e: (not e.is_dir(), e.name)):
                    if entry.name.startswith("."):
                        continue
                    entries.append({
                        "type": "dir" if entry.is_dir() else "file",
                        "path": os.path.relpath(entry.path, self.workspace_root),
                        "size": entry.stat().st_size if entry.is_file() else None,
                    })

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"path": os.path.relpath(full_path, self.workspace_root), "count": len(entries), "entries": entries},
        )
