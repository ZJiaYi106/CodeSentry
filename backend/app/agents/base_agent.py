"""Base class for sub-agents — every sub-agent has a restricted tool set and role.

Sub-agents call the LLM via _llm_call(), which handles the tool-calling loop:
  LLM → tool_calls → execute tools → ToolMessage → LLM → ... → final text
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class SubAgentResult:
    """Structured result from a sub-agent invocation."""

    agent_name: str
    success: bool
    output: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    duration_ms: float = 0.0


class BaseSubAgent:
    """Abstract base for sub-agents.

    Each sub-agent:
      - Has a name and role description (system prompt)
      - Gets a restricted list of tool NAMES that it may call
      - Reports results back to the Orchestrator
      - Cannot directly execute HIGH-risk tools without Orchestrator approval
    """

    name: str = "base"
    description: str = ""
    allowed_tools: list[str] = []  # tool names this agent may use

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self._registry = ToolRegistry(workspace_root)

    @property
    def tools(self) -> list[Any]:
        """Return the tool instances this agent is allowed to use."""
        return [
            self._registry.get(name)
            for name in self.allowed_tools
            if name in self._registry
        ]

    @property
    def system_prompt(self) -> str:
        """Return the system prompt for this agent. Override in subclasses."""
        return (
            f"You are {self.name}, a sub-agent of CodeSentry. "
            f"{self.description}\n\n"
            f"You may only use the following tools: {', '.join(self.allowed_tools)}. "
            f"Do not attempt to use other tools. "
            f"Report your findings clearly and concisely."
        )

    # ── LLM tool-calling loop ────────────────────────────────

    async def _llm_call(
        self, task: str, max_rounds: int = 6
    ) -> tuple[str, list[dict[str, Any]]]:
        """Call the LLM with this agent's tools, handling the tool-calling loop.

        Pattern: tool-calling call → execute tools → text-only call → result.
        This two-step pattern ensures the LLM converges to a text answer
        instead of looping on tool calls forever.

        Returns (final_text_output, tool_call_records).
        """
        from app.models.provider import get_model

        model = get_model()

        # Build tool schemas and name→instance map for this agent
        tool_schemas: list[dict[str, Any]] = []
        tool_map: dict[str, Any] = {}
        for name in self.allowed_tools:
            try:
                tool = self._registry.get(name)
                tool_schemas.append(tool.to_openai_function())
                tool_map[name] = tool
            except KeyError:
                logger.warning("Tool '%s' not found in registry, skipping", name)

        if not tool_schemas:
            logger.warning("%s has no tools available", self.name)
            return f"[{self.name}] No tools available.", []

        conversation: list = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=task),
        ]

        tool_calls_record: list[dict[str, Any]] = []

        for round_num in range(max_rounds):
            # ── Step A: Call WITH tools ──────────────────────
            logger.info("%s | round %d: calling with tools", self.name, round_num + 1)

            try:
                model_with_tools = model.bind_tools(tool_schemas)
                response = await model_with_tools.ainvoke(conversation)
            except Exception as exc:
                logger.error("%s | LLM call failed in round %d: %s", self.name, round_num, exc)
                return (
                    f"[{self.name}] LLM call failed: {exc}",
                    tool_calls_record,
                )

            # If NO tool calls — this is a text response, return it
            if not (hasattr(response, "tool_calls") and response.tool_calls):
                content = self._extract_text(response)
                logger.info("%s | done (no tool calls) in round %d", self.name, round_num + 1)
                return content, tool_calls_record

            # ── Step B: Execute all tool calls ───────────────
            conversation.append(response)

            for tc in response.tool_calls:
                tool_name: str = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                tool_args: dict = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                tc_id: str = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")

                logger.info(
                    "%s | executing: %s(%s)",
                    self.name, tool_name,
                    json.dumps(tool_args, ensure_ascii=False)[:200],
                )

                if tool_name in tool_map:
                    try:
                        result = await tool_map[tool_name].run(**tool_args)
                        tool_calls_record.append(result.to_dict())
                        conversation.append(ToolMessage(
                            content=json.dumps(result.data, ensure_ascii=False, default=str),
                            tool_call_id=tc_id,
                        ))
                    except Exception as exc:
                        logger.error("%s | tool error: %s", self.name, exc)
                        conversation.append(ToolMessage(
                            content=f"Tool execution error: {exc}",
                            tool_call_id=tc_id,
                        ))
                else:
                    conversation.append(ToolMessage(
                        content=f"Tool '{tool_name}' not available. Allowed: {', '.join(self.allowed_tools)}",
                        tool_call_id=tc_id,
                    ))

            # ── Step C: Text-only call to produce answer ─────
            conversation.append(HumanMessage(
                content="以上是工具返回的结果。现在请用纯文本给出最终回答。"
                "不要使用 <invoke> <parameter> 等 XML 标签，不要调用工具，"
                "直接用 markdown 格式总结你发现的内容并回答原始任务。"
            ))

            try:
                final_response = await model.ainvoke(conversation)
            except Exception as exc:
                logger.error("%s | text-only call failed: %s", self.name, exc)
                return (
                    f"[{self.name}] Error getting final response: {exc}",
                    tool_calls_record,
                )

            # If the text-only response also has tool_calls (model ignored our nudge),
            # strip the nudge, keep the tool_call response, and loop again
            if hasattr(final_response, "tool_calls") and final_response.tool_calls:
                logger.warning("%s | model ignored text-only nudge, looping", self.name)
                conversation.pop()  # remove the nudge message
                continue

            content = self._extract_text(final_response)
            logger.info("%s | done in round %d", self.name, round_num + 1)
            return content, tool_calls_record

        logger.warning("%s | max rounds (%d) reached", self.name, max_rounds)
        return (
            f"[{self.name}] Reached max rounds ({max_rounds}). Task may be too complex.",
            tool_calls_record,
        )

    @staticmethod
    def _extract_text(response: Any) -> str:
        """Extract text content from an LLM response, strip XML tool-call artifacts."""
        import re
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            content = "".join(
                c.get("text", "") if isinstance(c, dict) else str(c)
                for c in content
            )
        text = content or ""
        # Strip <invoke>...</invoke> and <parameter>...</parameter> XML blocks
        text = re.sub(r'<invoke[^>]*>.*?</invoke>', '', text, flags=re.DOTALL)
        text = re.sub(r'<parameter[^>]*>.*?</parameter>', '', text, flags=re.DOTALL)
        text = re.sub(r'</invoke>', '', text)
        return text.strip()

    # ── Main entry point ─────────────────────────────────────

    async def run(self, task_context: str) -> SubAgentResult:
        """Execute the sub-agent's task via LLM and return a structured result.

        Falls back to _fallback_run() if the LLM call fails entirely.
        """
        import time

        start = time.perf_counter()
        logger.info("SUB-AGENT | %s starting (tools=%s)", self.name, self.allowed_tools)

        try:
            output, tool_calls = await self._llm_call(task_context)
            success = True
        except Exception as exc:
            logger.exception("%s | LLM call failed, using fallback: %s", self.name, exc)
            output = self._fallback_run(task_context)
            tool_calls = []
            success = False

        duration = (time.perf_counter() - start) * 1000

        return SubAgentResult(
            agent_name=self.name,
            success=success,
            output=output,
            tool_calls=tool_calls,
            duration_ms=duration,
        )

    def _fallback_run(self, task_context: str) -> str:
        """Deterministic fallback — used if LLM is unavailable.

        Override in subclasses for richer behavior.
        """
        return (
            f"[{self.name}] Would analyze task: {task_context[:200]}\n"
            f"Allowed tools: {', '.join(self.allowed_tools)}\n"
            f"Workspace: {self.workspace_root}"
        )
