"""View git diff within the workspace (read-only)."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from app.tools.base import BaseTool, RiskLevel, ToolParameter, ToolResult


class GitDiffTool(BaseTool):
    name = "git_diff"
    description = "Show the current git diff (unstaged and staged changes) within the workspace."
    risk_level = RiskLevel.LOW
    parameters = [
        ToolParameter(name="staged", type="boolean", description="Show only staged changes (default: false)", required=False, default=False),
        ToolParameter(name="path", description="Limit diff to a specific file/path", required=False),
    ]

    async def execute(self, **kwargs: Any) -> ToolResult:
        staged: bool = bool(kwargs.get("staged", False))
        path: str | None = kwargs.get("path")  # already resolved by base.run() if present

        cmd = ["git", "-C", self.workspace_root, "diff"]
        if staged:
            cmd.append("--staged")
        if path:
            cmd.append("--")
            cmd.append(os.path.relpath(path, self.workspace_root))

        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=15,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        except asyncio.TimeoutError:
            return ToolResult(tool_name=self.name, success=False, error="git diff timed out")
        except FileNotFoundError:
            return ToolResult(tool_name=self.name, success=False, error="git is not installed or not on PATH")
        except Exception as exc:
            return ToolResult(tool_name=self.name, success=False, error=str(exc))

        stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""
        if proc.returncode != 0 and stderr_str:
            return ToolResult(tool_name=self.name, success=False, error=stderr_str.strip())

        diff_output = stdout.decode("utf-8", errors="replace")[:20_000] if stdout else ""

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "staged": staged,
                "path": path,
                "diff": diff_output,
                "empty": len(diff_output.strip()) == 0,
            },
        )
