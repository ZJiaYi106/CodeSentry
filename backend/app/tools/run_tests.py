"""Run test commands within the workspace.

Medium risk — executes shell commands, restricted to whitelisted test frameworks.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.tools.base import BaseTool, RiskLevel, ToolParameter, ToolResult

ALLOWED_COMMANDS = {
    "pytest",
    "python -m pytest",
    "python -m unittest",
    "npm test",
    "npm run test",
    "go test",
    "cargo test",
    "make test",
    "tox",
    "nox",
}


class RunTestsTool(BaseTool):
    name = "run_tests"
    description = (
        "Run a test command inside the workspace directory. "
        "Only whitelisted test frameworks are allowed."
    )
    risk_level = RiskLevel.MEDIUM
    parameters = [
        ToolParameter(name="command", description="Test command to run (e.g. 'pytest', 'python -m pytest tests/')"),
        ToolParameter(name="timeout_seconds", type="integer", description="Max execution time in seconds", required=False, default=60),
    ]

    async def execute(self, **kwargs: Any) -> ToolResult:
        command: str = kwargs.get("command", "")
        timeout: int = int(kwargs.get("timeout_seconds", 60))

        # Validate command is in whitelist (prefix match)
        cmd_base = command.strip().split(" --")[0].split(" -")[0].rstrip()
        if not any(cmd_base.startswith(allowed) for allowed in ALLOWED_COMMANDS):
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Command '{cmd_base}' is not in the allowed test command whitelist. "
                      f"Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}",
            )

        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.workspace_root,
                ),
                timeout=timeout,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Test command timed out after {timeout}s",
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to run command: {exc}",
            )

        stdout_str = stdout.decode("utf-8", errors="replace")[:10_000] if stdout else ""
        stderr_str = stderr.decode("utf-8", errors="replace")[:5_000] if stderr else ""

        return ToolResult(
            tool_name=self.name,
            success=proc.returncode == 0,
            data={
                "command": command,
                "exit_code": proc.returncode,
                "stdout": stdout_str,
                "stderr": stderr_str,
            },
        )
