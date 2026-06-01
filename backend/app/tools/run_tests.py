"""Run test commands within the workspace.

Medium risk — executes shell commands, restricted to whitelisted test frameworks.
"""

from __future__ import annotations

import asyncio
import shlex
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

# Pre-split allowed base commands into token tuples for exact matching.
_ALLOWED_TOKEN_PREFIXES: list[tuple[str, ...]] = [
    tuple(cmd.split()) for cmd in sorted(ALLOWED_COMMANDS, key=len, reverse=True)
]

# Shell metacharacters that would allow command chaining / substitution.
# Their presence is rejected outright — test commands must be a single
# whitelist command followed by arguments, never a shell pipeline.
SHELL_META = set(";&|`$()<>\\\n\r")


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

        # ── Validate command: reject shell metacharacters, then exact-match
        # the leading tokens against the whitelist.
        #
        # Why not prefix-match on the raw string: `pytest --x ; rm -rf /`
        # used to pass because we stripped at " -" and only checked "pytest",
        # but create_subprocess_shell ran the WHOLE string including the
        # chained `rm`. Now we forbid metacharacters entirely and require the
        # command's leading tokens to equal a whitelisted framework.
        if any(ch in command for ch in SHELL_META):
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=(
                    "Command rejected: contains shell metacharacters "
                    f"({sorted(c for c in SHELL_META if c in command)}). "
                    "Only a single whitelisted test command plus arguments is allowed."
                ),
            )

        try:
            tokens = shlex.split(command)
        except ValueError as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Command could not be parsed: {exc}",
            )

        if not tokens:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Command is empty.",
            )

        # The leading tokens must exactly match one of the allowed base commands.
        if not any(
            tuple(tokens[: len(prefix)]) == prefix for prefix in _ALLOWED_TOKEN_PREFIXES
        ):
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=(
                    f"Command '{tokens[0]}' is not in the allowed test command whitelist. "
                    f"Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}"
                ),
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
