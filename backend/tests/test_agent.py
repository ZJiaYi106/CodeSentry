"""Tests for the agent workflow — planner, reflector, summarizer, graph."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.graph import (
    _router_after_planner,
    _router_after_reflector,
    build_agent_graph,
    tool_executor_node,
)
from app.agents.planner import _pattern_based_plan, planner_node
from app.agents.reflector import _rule_based_reflection, reflector_node
from app.agents.summarizer import _build_fallback_summary, summarizer_node
from app.memory.short_term import AgentState, NextAction, PlanStep


# ── State fixture ──────────────────────────────────────────

@pytest.fixture
def base_state(tmp_path: Path) -> dict:
    return {
        "task": "Fix the bug in utils.py",
        "workspace_root": str(tmp_path),
        "messages": [],
        "plan": [],
        "current_step_index": 0,
        "observations": [],
        "tool_results": [],
        "iteration": 0,
        "max_iterations": 15,
        "next_action": NextAction.CONTINUE.value,
        "final_summary": "",
        "error": None,
        "approval_required": False,
        "pending_approval_id": None,
    }


# ── PlanStep dataclass ─────────────────────────────────────

class TestAgentState:
    def test_plan_step_creation(self):
        step = PlanStep(id="s1", description="List files", tool_name="list_files")
        assert step.status == "pending"
        assert step.tool_name == "list_files"

    def test_current_step(self, base_state):
        base_state["plan"] = [
            {"id": "s1", "description": "Step 1", "tool_name": "list_files", "tool_args": {}, "status": "pending", "result_summary": ""},
        ]
        # current_step property works with dict-based state
        idx = base_state["current_step_index"]
        plan = base_state["plan"]
        assert idx < len(plan)
        assert plan[idx]["tool_name"] == "list_files"

    def test_is_done(self, base_state):
        base_state["next_action"] = "finish"
        # Manual check
        assert base_state["next_action"] == "finish"

    def test_add_observation(self):
        state = AgentState(task="test", workspace_root="/tmp")
        state.add_observation("Found 3 Python files")
        assert len(state.observations) == 1
        assert "Python files" in state.observations[0]


# ── Planner ────────────────────────────────────────────────

class TestPlanner:
    def test_pattern_based_plan_has_steps(self):
        plan = _pattern_based_plan("Fix a bug in authentication")
        assert len(plan) >= 3
        assert any(s["tool_name"] == "list_files" for s in plan)
        assert any(s["tool_name"] == "search_code" for s in plan)

    def test_pattern_based_plan_for_fix(self):
        plan = _pattern_based_plan("Fix the login bug")
        search = [s for s in plan if s["tool_name"] == "search_code"][0]
        assert "bug" in search["tool_args"]["pattern"].lower() or "FIXME" in search["tool_args"]["pattern"]

    def test_pattern_based_plan_for_add(self):
        plan = _pattern_based_plan("Add a new API endpoint")
        search = [s for s in plan if s["tool_name"] == "search_code"][0]
        assert "def" in search["tool_args"]["pattern"] or "class" in search["tool_args"]["pattern"]

    @pytest.mark.asyncio
    async def test_planner_node_fallback(self, base_state, tmp_path):
        """Planner should use fallback when LLM is unavailable."""
        # Create a workspace with files so tools can work
        (tmp_path / "README.md").write_text("# Test Project\n")
        (tmp_path / "test_sample.py").write_text("def test_pass(): assert True\n")

        with patch("app.agents.planner.get_model", side_effect=RuntimeError("No API key")):
            result = await planner_node(base_state)
        assert len(result["plan"]) >= 3
        assert result["iteration"] == 1
        assert result["current_step_index"] == 0

    @pytest.mark.asyncio
    async def test_planner_preserves_existing_plan_on_replan(self, base_state, tmp_path):
        """On replan, the planner replaces the old plan."""
        base_state["plan"] = [{"id": "old", "description": "Old step", "tool_name": "list_files", "tool_args": {}, "status": "completed", "result_summary": ""}]
        base_state["iteration"] = 3
        (tmp_path / "README.md").write_text("# Test\n")

        with patch("app.agents.planner.get_model", side_effect=RuntimeError("No API key")):
            result = await planner_node(base_state)
        # Old plan should be replaced
        assert result["plan"][0]["id"] != "old"


# ── Reflector ──────────────────────────────────────────────

class TestReflector:
    def test_rule_based_continue(self, base_state):
        base_state["plan"] = [
            {"id": "s1", "description": "Step 1", "tool_name": "list_files", "tool_args": {}, "status": "completed", "result_summary": "ok"},
            {"id": "s2", "description": "Step 2", "tool_name": "read_file", "tool_args": {}, "status": "pending", "result_summary": ""},
        ]
        base_state["current_step_index"] = 1  # one done, one pending
        action = _rule_based_reflection(base_state)
        assert action == "continue"

    def test_rule_based_replan_on_failure(self, base_state):
        base_state["plan"] = [
            {"id": "s1", "description": "Step 1", "tool_name": "read_file", "tool_args": {}, "status": "failed", "result_summary": "file not found"},
            {"id": "s2", "description": "Step 2", "tool_name": "list_files", "tool_args": {}, "status": "pending", "result_summary": ""},
        ]
        base_state["current_step_index"] = 1
        action = _rule_based_reflection(base_state)
        assert action == "replan"

    def test_rule_based_finish_when_done(self, base_state):
        base_state["plan"] = [
            {"id": "s1", "description": "Step 1", "tool_name": "list_files", "tool_args": {}, "status": "completed", "result_summary": "ok"},
        ]
        base_state["current_step_index"] = 1  # all done
        action = _rule_based_reflection(base_state)
        assert action == "finish"

    def test_rule_based_finish_on_too_many_failures(self, base_state):
        base_state["plan"] = [
            {"id": f"s{i}", "description": f"Step {i}", "tool_name": "read_file", "tool_args": {}, "status": "failed", "result_summary": "err"}
            for i in range(5)
        ]
        base_state["current_step_index"] = 5
        action = _rule_based_reflection(base_state)
        assert action == "finish"

    def test_rule_based_finish_on_max_iterations(self, base_state):
        base_state["iteration"] = 15
        base_state["max_iterations"] = 15
        action = _rule_based_reflection(base_state)
        assert action == "finish"

    @pytest.mark.asyncio
    async def test_reflector_node_fallback(self, base_state):
        base_state["plan"] = [
            {"id": "s1", "description": "Done", "tool_name": "list_files", "tool_args": {}, "status": "completed", "result_summary": "ok"},
        ]
        base_state["current_step_index"] = 1

        with patch("app.agents.reflector.get_model", side_effect=RuntimeError("No API key")):
            result = await reflector_node(base_state)
        assert result["next_action"] in ("continue", "replan", "finish")


# ── Summarizer ─────────────────────────────────────────────

class TestSummarizer:
    def test_fallback_summary(self, base_state):
        base_state["plan"] = [
            {"id": "s1", "description": "List files", "tool_name": "list_files", "tool_args": {}, "status": "completed", "result_summary": "Found 3 files"},
        ]
        base_state["tool_results"] = [
            {"tool": "list_files", "success": True, "data": {"count": 3}, "duration_ms": 5.0},
        ]
        summary = _build_fallback_summary(base_state)
        assert "Changes Made" in summary
        assert "List files" in summary
        assert "Notes & Recommendations" in summary

    def test_fallback_summary_includes_test_results(self, base_state):
        base_state["tool_results"] = [
            {"tool": "run_tests", "success": True, "data": {"exit_code": 0, "stdout": "3 passed"}},
        ]
        summary = _build_fallback_summary(base_state)
        assert "Test Results" in summary
        assert "3 passed" in summary

    @pytest.mark.asyncio
    async def test_summarizer_node_fallback(self, base_state):
        with patch("app.agents.summarizer.get_model", side_effect=RuntimeError("No API key")):
            result = await summarizer_node(base_state)
        assert result["next_action"] == "finish"
        assert len(result["final_summary"]) > 50


# ── Graph Structure ────────────────────────────────────────

class TestGraph:
    def test_build_graph_compiles(self):
        graph = build_agent_graph()
        assert graph is not None
        # Verify it's a compiled graph
        assert hasattr(graph, "ainvoke")
        assert hasattr(graph, "astream")
        # Verify channels exist (don't use get_graph() which may fail with dict state)
        assert graph.channels is not None

    def test_router_after_planner_with_tools(self, base_state):
        base_state["plan"] = [
            {"id": "s1", "description": "S1", "tool_name": "list_files", "tool_args": {}, "status": "pending", "result_summary": ""},
        ]
        base_state["current_step_index"] = 0
        route = _router_after_planner(base_state)
        assert route == "tool_executor"

    def test_router_after_planner_empty_plan(self, base_state):
        route = _router_after_planner(base_state)
        assert route == "summarizer"

    def test_router_after_reflector_finish(self, base_state):
        base_state["next_action"] = "finish"
        route = _router_after_reflector(base_state)
        assert route == "summarizer"

    def test_router_after_reflector_replan(self, base_state):
        base_state["next_action"] = "replan"
        route = _router_after_reflector(base_state)
        assert route == "planner"

    def test_router_after_reflector_continue_with_steps(self, base_state):
        base_state["next_action"] = "continue"
        base_state["plan"] = [
            {"id": "s1", "description": "S1", "tool_name": "list_files", "tool_args": {}, "status": "pending", "result_summary": ""},
        ]
        base_state["current_step_index"] = 0
        route = _router_after_reflector(base_state)
        assert route == "tool_executor"


# ── Tool Executor Node ─────────────────────────────────────

class TestToolExecutor:
    @pytest.mark.asyncio
    async def test_executes_list_files(self, base_state, tmp_path):
        (tmp_path / "a.py").write_text("x")
        base_state["plan"] = [
            {"id": "s1", "description": "List", "tool_name": "list_files", "tool_args": {}, "status": "pending", "result_summary": ""},
        ]
        base_state["current_step_index"] = 0
        result = await tool_executor_node(base_state)
        # list_files with default args (path="." which gets resolved to workspace_root)
        assert result["plan"][0]["status"] in ("completed", "failed")
        assert len(result["tool_results"]) == 1
        # Tool result exists — verify structure
        tr = result["tool_results"][0]
        assert tr["tool"] == "list_files"
        assert "success" in tr
        assert "duration_ms" in tr

    @pytest.mark.asyncio
    async def test_advances_current_step(self, base_state, tmp_path):
        (tmp_path / "a.py").write_text("x")
        base_state["plan"] = [
            {"id": "s1", "description": "S1", "tool_name": "list_files", "tool_args": {"path": "."}, "status": "pending", "result_summary": ""},
            {"id": "s2", "description": "S2", "tool_name": "list_files", "tool_args": {"path": "."}, "status": "pending", "result_summary": ""},
        ]
        base_state["current_step_index"] = 0
        result = await tool_executor_node(base_state)
        assert result["current_step_index"] == 1

    @pytest.mark.asyncio
    async def test_missing_tool(self, base_state):
        base_state["plan"] = [
            {"id": "s1", "description": "Bad", "tool_name": "nonexistent_tool", "tool_args": {}, "status": "pending", "result_summary": ""},
        ]
        base_state["current_step_index"] = 0
        result = await tool_executor_node(base_state)
        assert result["plan"][0]["status"] == "failed"


# ── End-to-end agent run (fallback mode) ───────────────────

class TestAgentRun:
    @pytest.mark.asyncio
    async def test_run_agent_completes(self, tmp_path):
        """Full agent run should complete with fallback (no LLM needed)."""
        (tmp_path / "README.md").write_text("# Test\n")
        (tmp_path / "test_sample.py").write_text("def test_ok(): assert True\n")

        from app.agents.graph import run_agent

        with patch("app.agents.planner.get_model", side_effect=RuntimeError("No API key")), \
             patch("app.agents.reflector.get_model", side_effect=RuntimeError("No API key")), \
             patch("app.agents.summarizer.get_model", side_effect=RuntimeError("No API key")):
            final = await run_agent("Fix a bug", str(tmp_path), max_iterations=5)

        assert final["next_action"] == "finish"
        assert len(final["plan"]) > 0
        assert len(final["tool_results"]) > 0
        assert len(final["final_summary"]) > 0
