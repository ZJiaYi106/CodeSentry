"""Central Orchestrator — plans, delegates, approves, and controls quality.

The Orchestrator is the ONLY agent that:
  - Sees the full picture
  - Coordinates sub-agents
  - Grants or denies approval for risky operations
  - Synthesizes final results
  - Enforces the security boundary

Sub-agents (RepoAnalyst, Implementer, Reviewer) have RESTRICTED tool sets
and CANNOT directly execute writes or high-risk commands.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.agents.implementer import Implementer
from app.agents.repo_analyst import RepoAnalyst
from app.agents.reviewer import Reviewer
from app.security.approval_gate import AutoApproveGate, EmitFn, _BaseGate
from app.security.permissions import (
    ApprovalRequest,
    RiskLevel,
    is_tool_allowed,
)
from app.audit.logger import log_event

logger = logging.getLogger(__name__)


class OrchestratorPhase(str, Enum):
    ANALYZE = "analyze"
    IMPLEMENT = "implement"
    REVIEW = "review"
    DONE = "done"


class TaskIntent(str, Enum):
    """Task intent classified before running the pipeline."""

    ANALYSIS = "analysis"        # read-only: only the analyst runs
    MODIFICATION = "modification"  # full pipeline: analyze + implement + review
    UNKNOWN = "unknown"          # conservative: full pipeline


# Keywords marking a read-only analysis / Q&A task. Kept conservative —
# ambiguous words like "检查" (check) are deliberately absent.
_ANALYSIS_KEYWORDS = (
    "分析", "解释", "说明", "讲解", "查看", "看看", "了解", "理解",
    "是什么", "做什么", "为什么", "怎么样", "如何", "评估", "总结", "报告",
    "介绍", "梳理", "解读", "讲解", "架构", "原理", "作用", "干嘛",
    "analyze", "explain", "describe", "what is", "what does", "why",
    "how does", "how do", "review", "evaluate", "summarize",
    "understand", "inspect", "overview", "architecture",
)

_MODIFICATION_KEYWORDS = (
    "修复", "修改", "添加", "新增", "增加", "删除", "移除", "重构",
    "实现", "编写", "创建", "优化", "改进", "升级", "重命名", "迁移",
    "改一", "改成", "改下", "改掉", "加上", "补上", "加上", "生成",
    "fix", "add", "remove", "delete", "refactor", "implement", "create",
    "write", "modify", "update", "change", "optimize", "improve",
    "rename", "generate", "patch", "migrate",
)


def classify_task_intent(task: str) -> TaskIntent:
    """Classify a user task as read-only analysis vs code modification.

    Modification keywords win over analysis keywords (e.g. "分析并修复 bug"
    must run the full pipeline). Falls back to UNKNOWN when nothing matches.
    """
    task_lower = task.lower()
    if any(k in task_lower for k in _MODIFICATION_KEYWORDS):
        return TaskIntent.MODIFICATION
    if any(k in task_lower for k in _ANALYSIS_KEYWORDS):
        return TaskIntent.ANALYSIS
    return TaskIntent.UNKNOWN


@dataclass
class OrchestratorResult:
    """Full result from an orchestrator run."""

    task: str
    success: bool
    intent: str = TaskIntent.UNKNOWN.value
    phases: list[dict[str, Any]] = field(default_factory=list)
    analyst_result: Any = None
    implementer_result: Any = None
    reviewer_result: Any = None
    approvals: list[ApprovalRequest] = field(default_factory=list)
    final_summary: str = ""
    error: str | None = None
    total_duration_ms: float = 0.0


class Orchestrator:
    """Central coordinator for the CodeSentry multi-agent system.

    Workflow:
      1. ANALYZE  → RepoAnalyst explores the codebase
      2. IMPLEMENT → Implementer proposes changes (writes gated)
      3. REVIEW    → Reviewer validates + runs tests (execution gated)
      4. DONE      → Synthesize results
    """

    def __init__(
        self,
        workspace_root: str,
        auto_approve_risk: RiskLevel = RiskLevel.LOW,
        approval_gate: _BaseGate | None = None,
        emit: EmitFn | None = None,
    ):
        self.workspace_root = workspace_root
        self.auto_approve_risk = auto_approve_risk
        # When no human is in the loop (demos / direct usage / tests), default
        # to AutoApproveGate so gated tools still run — but every auto-approval
        # is recorded as AUTO_APPROVED, making it visible and auditable.
        self.approval_gate: _BaseGate = approval_gate or AutoApproveGate()
        # Live SSE event sink shared with sub-agents (progress / tool_call).
        self._emit = emit
        self.analyst = RepoAnalyst(workspace_root, auto_approve_risk, self.approval_gate, emit)
        self.implementer = Implementer(workspace_root, auto_approve_risk, self.approval_gate, emit)
        self.reviewer = Reviewer(workspace_root, auto_approve_risk, self.approval_gate, emit)
        self.approvals: list[ApprovalRequest] = []

        # Enforce tool-isolation invariant at construction time (was dead code).
        self._validate_sub_agent_tools(self.analyst.name, self.analyst.allowed_tools)
        self._validate_sub_agent_tools(self.implementer.name, self.implementer.allowed_tools)
        self._validate_sub_agent_tools(self.reviewer.name, self.reviewer.allowed_tools)

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Push a live event to the SSE stream if a sink is wired in."""
        if self._emit is None:
            return
        try:
            self._emit(event_type, data)
        except Exception:  # never let SSE plumbing break the pipeline
            logger.debug("ORCHESTRATOR | emit failed", exc_info=True)

    # ── Sub-agent tool restrictions ────────────────────────

    def _validate_sub_agent_tools(self, agent_name: str, allowed: list[str]) -> None:
        """Ensure a sub-agent's tools are all on the permission whitelist.

        Raises ValueError if the sub-agent uses an unknown tool.  Called in
        __init__ so the isolation invariant is enforced, not just documented.
        """
        for tool_name in allowed:
            if not is_tool_allowed(tool_name):
                raise ValueError(
                    f"Sub-agent '{agent_name}' uses unknown tool '{tool_name}'"
                )

    # ── Main execution ─────────────────────────────────────

    async def run(self, task: str) -> OrchestratorResult:
        """Execute the full multi-agent workflow."""
        start = time.perf_counter()
        result = OrchestratorResult(task=task, success=True)

        intent = classify_task_intent(task)
        result.intent = intent.value

        logger.info(
            "ORCHESTRATOR | starting task (intent=%s): %s...",
            intent.value, task[:100],
        )

        intent_label = {
            TaskIntent.ANALYSIS.value: "只读分析",
            TaskIntent.MODIFICATION.value: "代码修改",
            TaskIntent.UNKNOWN.value: "通用任务",
        }.get(intent.value, intent.value)
        self._emit_event("progress", {
            "message": f"任务已判定为「{intent_label}」，正在规划执行流程…",
            "percent": 12,
        })

        # ── Retrieve long-term memory for context ────────────
        memory_context = ""
        self._emit_event("progress", {
            "message": "正在检索长期记忆中的历史经验（修复模式 / 项目约定 / 用户偏好）…",
            "percent": 15,
        })
        try:
            from app.memory.long_term import search_memories

            # fix_patterns and project_conventions are workspace-scoped:
            # one project's experience must never leak into another project.
            # user_preferences stay global (they describe the user, not a repo).
            fix_results = await search_memories(task, "fix_patterns", n_results=2, workspace_root=self.workspace_root)
            convention_results = await search_memories(task, "project_conventions", n_results=2, workspace_root=self.workspace_root)
            pref_results = await search_memories(task, "user_preferences", n_results=1)

            parts = []
            if fix_results:
                parts.append("Similar past fixes:\n" + "\n".join(f"- {r['content'][:250]}" for r in fix_results))
            if convention_results:
                parts.append("Project conventions:\n" + "\n".join(f"- {r['content'][:250]}" for r in convention_results))
            if pref_results:
                parts.append("User preferences:\n" + "\n".join(f"- {r['content'][:250]}" for r in pref_results))
            if parts:
                memory_context = "\n\nRelevant past experience:\n" + "\n".join(parts)
                logger.info("ORCHESTRATOR | injected memory: %d fix + %d convention + %d pref",
                             len(fix_results), len(convention_results), len(pref_results))
                self._emit_event("progress", {
                    "message": (
                        f"检索到 {len(fix_results)} 条修复经验、{len(convention_results)} 条项目约定、"
                        f"{len(pref_results)} 条用户偏好，将注入任务上下文"
                    ),
                    "percent": 18,
                })
            else:
                self._emit_event("progress", {
                    "message": "未找到相关历史经验，将从头分析",
                    "percent": 18,
                })
        except Exception as exc:
            logger.debug("ORCHESTRATOR | memory search skipped: %s", exc)

        # Augment task with memory context for sub-agents
        augmented_task = task + memory_context

        try:
            # Phase 1: ANALYZE
            result.phases.append({"phase": "analyze", "status": "running"})
            self._emit_event("progress", {
                "message": "【分析阶段】仓库分析师开始探索代码仓库：查看目录结构、阅读关键文件、搜索相关代码…",
                "percent": 20,
            })
            analyst_result = await self.analyst.run(augmented_task)
            result.analyst_result = analyst_result
            result.phases[-1]["status"] = "completed"
            result.phases[-1]["output"] = analyst_result.output[:500]
            log_event(
                event_type="phase_complete",
                agent="orchestrator",
                extra={"phase": "analyze", "duration_ms": analyst_result.duration_ms},
            )
            logger.info("ORCHESTRATOR | analyze complete (%d ms)", analyst_result.duration_ms)
            self._emit_event("progress", {
                "message": (
                    f"【分析阶段】完成，耗时 {analyst_result.duration_ms / 1000:.1f} 秒，"
                    f"共调用 {len(analyst_result.tool_calls)} 次工具"
                ),
                "percent": 40,
            })

            # ── Intent gate: read-only tasks skip implement + review ──
            if intent == TaskIntent.ANALYSIS:
                logger.info("ORCHESTRATOR | read-only task — skipping implement/review phases")
                self._emit_event("progress", {
                    "message": "该任务是只读分析，跳过实现与审查阶段，直接整理报告",
                    "percent": 60,
                })
                result.phases.append({
                    "phase": "implement",
                    "status": "skipped",
                    "output": "只读任务（分析/问答），跳过实现阶段",
                })
                result.phases.append({
                    "phase": "review",
                    "status": "skipped",
                    "output": "只读任务，无需审查与测试",
                })
            else:
                # Build context for downstream agents: task + analyst findings
                analyst_context = (
                    f"{augmented_task}\n\n"
                    f"=== 仓库分析师发现 ===\n{analyst_result.output[:1500]}"
                )

                # Phase 2: IMPLEMENT — receives analyst context
                result.phases.append({"phase": "implement", "status": "running"})
                self._emit_event("progress", {
                    "message": "【实现阶段】代码实现者正在阅读相关文件、规划修改方案（所有写入操作需你批准）…",
                    "percent": 50,
                })
                implementer_result = await self.implementer.run(analyst_context)
                result.implementer_result = implementer_result
                result.phases[-1]["status"] = "completed"
                result.phases[-1]["output"] = implementer_result.output[:500]

                log_event(
                    event_type="phase_complete",
                    agent="orchestrator",
                    extra={"phase": "implement", "duration_ms": implementer_result.duration_ms},
                )
                logger.info("ORCHESTRATOR | implement complete (%d ms)", implementer_result.duration_ms)
                self._emit_event("progress", {
                    "message": (
                        f"【实现阶段】完成，耗时 {implementer_result.duration_ms / 1000:.1f} 秒，"
                        f"共调用 {len(implementer_result.tool_calls)} 次工具"
                    ),
                    "percent": 65,
                })

                # Build reviewer context: task + analyst findings + implementer result
                reviewer_context = (
                    f"{augmented_task}\n\n"
                    f"=== 仓库分析师发现 ===\n{analyst_result.output[:1000]}\n\n"
                    f"=== 实现者操作 ===\n{implementer_result.output[:800]}"
                )

                # Phase 3: REVIEW — receives full context
                result.phases.append({"phase": "review", "status": "running"})
                self._emit_event("progress", {
                    "message": "【审查阶段】代码审查者正在检查变更、准备运行测试（测试执行需你批准）…",
                    "percent": 75,
                })
                reviewer_result = await self.reviewer.run(reviewer_context)
                result.reviewer_result = reviewer_result
                result.phases[-1]["status"] = "completed"
                result.phases[-1]["output"] = reviewer_result.output[:500]

                log_event(
                    event_type="phase_complete",
                    agent="orchestrator",
                    extra={"phase": "review", "duration_ms": reviewer_result.duration_ms},
                )
                logger.info("ORCHESTRATOR | review complete (%d ms)", reviewer_result.duration_ms)
                self._emit_event("progress", {
                    "message": (
                        f"【审查阶段】完成，耗时 {reviewer_result.duration_ms / 1000:.1f} 秒，"
                        f"共调用 {len(reviewer_result.tool_calls)} 次工具"
                    ),
                    "percent": 85,
                })

            # Phase 4: DONE — synthesize
            result.phases.append({"phase": "done", "status": "completed"})
            self._emit_event("progress", {
                "message": "正在汇总各阶段结果、生成最终报告…",
                "percent": 90,
            })
            result.final_summary = self._synthesize(task, result)
            result.success = True

            # Persist insights to long-term memory
            self._emit_event("progress", {
                "message": "正在将本次任务的经验写入长期记忆，供未来任务参考…",
                "percent": 95,
            })
            try:
                from app.memory.long_term import extract_and_store_insights
                await extract_and_store_insights(
                    task=task,
                    final_summary=result.final_summary,
                    files_involved=None,  # Could extract from tool results
                    workspace_root=self.workspace_root,
                )
            except Exception as mem_exc:
                logger.warning("Failed to store long-term memory: %s", mem_exc)

        except Exception as exc:
            logger.exception("ORCHESTRATOR | error: %s", exc)
            result.success = False
            result.error = str(exc)
            result.final_summary = f"Error during orchestration: {exc}"

        result.total_duration_ms = (time.perf_counter() - start) * 1000
        # Approvals were collected by the gate at execution time (real
        # interception), not after the fact.
        self.approvals = list(self.approval_gate.approvals)
        result.approvals = self.approvals

        log_event(
            event_type="orchestrator_complete",
            agent="orchestrator",
            success=result.success,
            duration_ms=result.total_duration_ms,
            extra={"phases": len(result.phases), "approvals": len(self.approvals)},
        )

        return result

    def _synthesize(self, task: str, result: OrchestratorResult) -> str:
        """Combine sub-agent outputs into a final summary.

        Smart synthesis: only show sections that add value.
        - Analyst report is always the main content.
        - Implementer only shown if it actually made changes.
        - Reviewer only shown if it ran tests or found issues.
        """
        parts = [f"# CodeSentry 报告", "", f"## 任务", f"{task}"]

        # ── Main analysis (always show) ──────────────────
        if result.analyst_result:
            parts.extend(["", result.analyst_result.output[:8000]])

        # ── Check if Implementer actually did something ──
        impl_has_changes = False
        if result.implementer_result:
            for tc in result.implementer_result.tool_calls:
                if tc.get("tool") == "write_patch" and tc.get("success"):
                    impl_has_changes = True
                    break

        if impl_has_changes:
            parts.extend(["", "## 代码变更", result.implementer_result.output[:4000]])

        # ── Check if Reviewer actually did something ─────
        rev_has_tests = False
        if result.reviewer_result:
            for tc in result.reviewer_result.tool_calls:
                if tc.get("tool") == "run_tests":
                    rev_has_tests = True
                    break
            # Also show if there are actual changes to review
            if impl_has_changes and not rev_has_tests:
                parts.extend(["", "## 审查", result.reviewer_result.output[:2000]])

        if rev_has_tests:
            parts.extend(["", "## 测试结果", result.reviewer_result.output[:4000]])

        # ── Approvals ────────────────────────────────────
        if self.approvals:
            parts.extend(["", "## 待审批"])
            for apr in self.approvals:
                parts.append(
                    f"- [{apr.risk_level.value.upper()}] `{apr.tool_name}` — {apr.reason} "
                    f"(状态: {apr.status.value})"
                )

        # ── Stats ────────────────────────────────────────
        completed = sum(1 for p in result.phases if p["status"] == "completed")
        intent_label = {
            TaskIntent.ANALYSIS.value: "只读分析",
            TaskIntent.MODIFICATION.value: "代码修改",
            TaskIntent.UNKNOWN.value: "通用任务",
        }.get(result.intent, result.intent)
        parts.extend([
            "",
            "---",
            f"任务类型: {intent_label}"
            f" | 阶段: {completed}/{len(result.phases)} 完成"
            f" | 耗时: {result.total_duration_ms:.0f}ms"
            f" | 审批: {len(self.approvals)} 项",
        ])

        return "\n".join(parts)
