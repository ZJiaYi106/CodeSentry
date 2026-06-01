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

from app.security.approval_gate import AutoApproveGate, EmitFn, _BaseGate
from app.security.permissions import RiskLevel, get_tool_risk, needs_approval
from app.tools.base import ToolResult
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

    def __init__(
        self,
        workspace_root: str,
        auto_approve_risk: RiskLevel = RiskLevel.LOW,
        approval_gate: _BaseGate | None = None,
        emit: EmitFn | None = None,
    ):
        self.workspace_root = workspace_root
        self._registry = ToolRegistry(workspace_root)
        self.auto_approve_risk = auto_approve_risk
        # None is resolved lazily to AutoApproveGate at first gated call, so
        # direct/demo usage (no human) stays non-blocking yet auditable.
        self.approval_gate = approval_gate
        # Live SSE event sink (progress / tool_call). None in direct usage.
        self._emit = emit

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Push a live event to the SSE stream if a sink is wired in."""
        if self._emit is None:
            return
        try:
            self._emit(event_type, data)
        except Exception:  # never let SSE plumbing break the agent
            logger.debug("%s | emit failed", self.name)

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

        Pattern: call WITH tools → execute any tool calls → loop. The model may
        keep calling tools across rounds (multi-round exploration) and finishes
        when it returns a text answer WITHOUT tool calls. A single text-only
        call is used only as a wrap-up when max_rounds is exhausted.

        Each individual LLM call has a 90-second asyncio hard deadline
        (in addition to the 120-second HTTP-level request_timeout on the model).

        Returns (final_text_output, tool_call_records).
        """
        import asyncio

        from app.models.provider import get_model

        LLM_CALL_TIMEOUT = 90  # seconds per individual LLM invocation

        model = get_model()

        async def _invoke_with_retry(
            awaitable_factory, attempts: int = 2
        ):
            """Invoke the LLM with a hard timeout, retrying once on timeout.

            Transient API slowness (especially on shared endpoints at peak
            hours) is common — a single retry recovers most of these.
            """
            last_exc: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return await asyncio.wait_for(
                        awaitable_factory(), timeout=LLM_CALL_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    last_exc = asyncio.TimeoutError(
                        f"LLM call timed out after {LLM_CALL_TIMEOUT}s"
                    )
                    logger.warning(
                        "%s | LLM call timed out (attempt %d/%d), retrying…",
                        self.name, attempt, attempts,
                    )
            raise last_exc  # type: ignore[misc]

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

        model_with_tools = model.bind_tools(tool_schemas)

        for round_num in range(max_rounds):
            # ── Call WITH tools ───────────────────────────────
            logger.info("%s | round %d: calling with tools", self.name, round_num + 1)
            self._emit_event("progress", {
                "message": (
                    f"{self.name} 正在思考下一步行动（第 {round_num + 1}/{max_rounds} 轮）…"
                ),
            })

            try:
                response = await _invoke_with_retry(
                    lambda: model_with_tools.ainvoke(conversation)
                )
            except asyncio.TimeoutError:
                logger.error("%s | LLM call timed out in round %d", self.name, round_num + 1)
                return (
                    f"[{self.name}] LLM call timed out after {LLM_CALL_TIMEOUT}s",
                    tool_calls_record,
                )
            except Exception as exc:
                logger.error("%s | LLM call failed in round %d: %s", self.name, round_num, exc)
                return (
                    f"[{self.name}] LLM call failed: {exc}",
                    tool_calls_record,
                )

            # If NO tool calls — the model has finished exploring; return its text.
            if not (hasattr(response, "tool_calls") and response.tool_calls):
                content = self._extract_text(response)
                logger.info("%s | done (no tool calls) in round %d", self.name, round_num + 1)
                return content, tool_calls_record

            # ── Execute all tool calls ─────────────────────────
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
                    # ── Approval gate: check BEFORE executing risky tools ──
                    # This is the real interception point. Tools whose risk
                    # exceeds the auto-approve threshold must be approved
                    # before they touch the filesystem / run commands.
                    try:
                        gated = needs_approval(tool_name, self.auto_approve_risk)
                    except ValueError:
                        gated = False  # unknown tool — handled by the else-branch below

                    if gated:
                        risk = get_tool_risk(tool_name)
                        gate = self.approval_gate or AutoApproveGate()
                        self.approval_gate = gate  # reuse for subsequent calls
                        decision = await gate.request(
                            tool_name, tool_args, self.name, risk
                        )
                        if not decision.approved:
                            logger.warning(
                                "%s | tool '%s' DENIED (%s) — not executed",
                                self.name, tool_name, decision.reason,
                            )
                            denied = ToolResult(
                                tool_name=tool_name,
                                success=False,
                                error=f"Approval denied: {decision.reason}",
                                risk_level=risk,
                            )
                            tool_calls_record.append(denied.to_dict())
                            self._emit_event("tool_call", {
                                "agent": self.name,
                                **denied.to_dict(),
                            })
                            conversation.append(ToolMessage(
                                content=(
                                    f"Tool '{tool_name}' was NOT approved "
                                    f"({decision.reason}) and was NOT executed. "
                                    f"Adjust your plan accordingly."
                                ),
                                tool_call_id=tc_id,
                            ))
                            continue  # skip execution, move to next tool call

                    try:
                        result = await tool_map[tool_name].run(**tool_args)
                        tool_calls_record.append(result.to_dict())
                        self._emit_event("tool_call", {
                            "agent": self.name,
                            **result.to_dict(),
                        })
                        conversation.append(ToolMessage(
                            content=json.dumps(result.data, ensure_ascii=False, default=str),
                            tool_call_id=tc_id,
                        ))
                    except Exception as exc:
                        logger.error("%s | tool error: %s", self.name, exc)
                        failed = ToolResult(
                            tool_name=tool_name,
                            success=False,
                            error=str(exc),
                        )
                        tool_calls_record.append(failed.to_dict())
                        self._emit_event("tool_call", {
                            "agent": self.name,
                            **failed.to_dict(),
                        })
                        conversation.append(ToolMessage(
                            content=f"Tool execution error: {exc}",
                            tool_call_id=tc_id,
                        ))
                else:
                    conversation.append(ToolMessage(
                        content=f"Tool '{tool_name}' not available. Allowed: {', '.join(self.allowed_tools)}",
                        tool_call_id=tc_id,
                    ))

            # ── Nudge: exploration may continue, or the model can finish ──
            conversation.append(HumanMessage(
                content=(
                    "工具执行结果已返回（见上方 ToolMessage）。"
                    "如果还需要更多信息才能完成任务，请在下一轮继续调用工具深入探索"
                    "（例如深入子目录、读取关键文件、搜索代码）；"
                    "如果信息已经足够，请直接输出最终结论，不要调用任何工具。"
                )
            ))

        # ── Max rounds reached: one final text-only call to wrap up ──
        logger.warning(
            "%s | max rounds (%d) reached — finalizing with a text-only call",
            self.name, max_rounds,
        )
        conversation.append(HumanMessage(
            content=(
                "已达到最大工具调用轮数。请基于已有的全部信息，用纯文本给出最终回答，"
                "不要使用 <invoke> <parameter> 等 XML 标签。"
            )
        ))
        try:
            final_response = await _invoke_with_retry(
                lambda: model.ainvoke(conversation)
            )
        except Exception as exc:
            logger.error("%s | final text-only call failed: %s", self.name, exc)
            return (
                f"[{self.name}] Reached max rounds ({max_rounds}). Task may be too complex.",
                tool_calls_record,
            )

        content = self._extract_text(final_response)
        logger.info("%s | done (max rounds wrap-up)", self.name)
        return content, tool_calls_record

    async def _execute_tool_with_approval(
        self, tool_name: str, tool_args: dict[str, Any]
    ) -> ToolResult:
        """Execute a tool, routing gated tools through the approval gate.

        Used by the rule-based fallbacks (no LLM configured) so that risky
        tools (write_patch / run_tests) still respect the approval boundary
        instead of silently executing.
        """
        tool = self._registry.get(tool_name)
        try:
            gated = needs_approval(tool_name, self.auto_approve_risk)
        except ValueError:
            gated = False
        if gated:
            risk = get_tool_risk(tool_name)
            gate = self.approval_gate or AutoApproveGate()
            self.approval_gate = gate
            decision = await gate.request(tool_name, tool_args, self.name, risk)
            if not decision.approved:
                return ToolResult(
                    tool_name=tool_name,
                    success=False,
                    error=f"Approval denied: {decision.reason}",
                    risk_level=risk,
                )
        return await tool.run(**tool_args)

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
