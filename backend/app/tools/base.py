"""Tool base classes and result types."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ToolResult:
    """Standardized result from any tool execution."""

    tool_name: str
    success: bool
    data: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool_name,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "risk_level": self.risk_level.value,
        }


class ToolParameter(BaseModel):
    """Description of a single tool parameter for LLM function-calling schemas."""

    name: str
    type: str = "string"
    description: str
    required: bool = True
    default: Any = None


class BaseTool(ABC):
    """Abstract base for all CodeSentry tools.

    Subclasses must define:
      - name: unique tool identifier
      - description: human-readable description for the LLM
      - risk_level: LOW / MEDIUM / HIGH
      - parameters: list of ToolParameter
      - execute(**kwargs) -> ToolResult
    """

    name: str = ""
    description: str = ""
    risk_level: RiskLevel = RiskLevel.LOW
    parameters: list[ToolParameter] = []

    def __init__(self, workspace_root: str):
        import os

        self.workspace_root = os.path.abspath(workspace_root)

    # ── Path safety ──────────────────────────────────────

    def _resolve_path(self, path: str) -> str:
        """Resolve `path` relative to workspace_root and validate it is within.

        Raises ValueError if the resolved path escapes the workspace.
        """
        import os

        # If path is absolute, join with workspace root's drive/root
        if os.path.isabs(path):
            # On Unix: /foo → /workspace/foo  (strip leading /)
            # On Windows: C:\foo → workspace\foo (strip drive)
            rel = path.lstrip(os.sep).replace(":", "")
            full = os.path.normpath(os.path.join(self.workspace_root, rel))
        else:
            full = os.path.normpath(os.path.join(self.workspace_root, path))

        # Check containment
        workspace_real = os.path.realpath(self.workspace_root)
        full_real = os.path.realpath(full)

        if not full_real.startswith(workspace_real + os.sep) and full_real != workspace_real:
            raise ValueError(
                f"Path traversal detected: '{path}' resolves outside workspace "
                f"({workspace_real}). Refusing."
            )
        return full

    # ── LLM schema ───────────────────────────────────────

    def to_openai_function(self) -> dict[str, Any]:
        """Return an OpenAI-compatible function/tool definition."""
        props: dict[str, Any] = {}
        required: list[str] = []

        for p in self.parameters:
            props[p.name] = {
                "type": p.type,
                "description": p.description,
            }
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }

    # ── Execution ────────────────────────────────────────

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with validated arguments.  Must be implemented."""
        ...

    def _fill_defaults(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Inject default values for any parameter not provided by the caller."""
        filled = dict(kwargs)
        for p in self.parameters:
            if p.name not in filled and p.default is not None:
                filled[p.name] = p.default
        return filled

    async def run(self, **kwargs: Any) -> ToolResult:
        """Validate, resolve paths, execute, time, and return result.

        Called by the agent.  Path-bearing parameters are resolved once here
        so that `execute()` receives already-validated absolute paths.
        """
        start = time.perf_counter()
        try:
            filled = self._fill_defaults(kwargs)
            # Resolve all path-bearing params to absolute, validated paths
            for key in ("path", "file_path", "directory", "target_file"):
                if key in filled and isinstance(filled[key], str):
                    filled[key] = self._resolve_path(filled[key])
        except ValueError as exc:
            duration = (time.perf_counter() - start) * 1000
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
                duration_ms=duration,
                risk_level=self.risk_level,
            )

        try:
            result = await self.execute(**filled)
        except Exception as exc:
            duration = (time.perf_counter() - start) * 1000
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=duration,
                risk_level=self.risk_level,
            )

        result.duration_ms = (time.perf_counter() - start) * 1000
        result.tool_name = self.name
        result.risk_level = self.risk_level
        return result
