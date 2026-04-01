"""Tests for multi-agent collaboration — sub-agents and orchestrator."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.base_agent import BaseSubAgent, SubAgentResult
from app.agents.implementer import Implementer
from app.agents.orchestrator import Orchestrator, OrchestratorPhase, OrchestratorResult
from app.agents.repo_analyst import RepoAnalyst
from app.agents.reviewer import Reviewer
from app.security.permissions import RiskLevel


# ── BaseSubAgent ───────────────────────────────────────────

class TestBaseSubAgent:
    def test_defaults(self, tmp_path: Path):
        agent = BaseSubAgent(workspace_root=str(tmp_path))
        assert agent.name == "base"
        assert agent.allowed_tools == []
        assert agent.system_prompt is not None

    def test_fallback_run(self, tmp_path: Path):
        agent = BaseSubAgent(workspace_root=str(tmp_path))
        result = agent._fallback_run("analyze this code")
        assert "analyze this code" in result
        assert str(tmp_path) in result

    @pytest.mark.asyncio
    async def test_run_returns_result(self, tmp_path: Path):
        agent = BaseSubAgent(workspace_root=str(tmp_path))
        result = await agent.run("task")
        assert isinstance(result, SubAgentResult)
        assert result.agent_name == "base"
        assert result.success


# ── RepoAnalyst ────────────────────────────────────────────

class TestRepoAnalyst:
    @pytest.mark.asyncio
    async def test_analyst_explores_repo(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("def main(): pass\n")
        (tmp_path / "utils.py").write_text("def helper(): pass\n")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "nested.py").write_text("# nested\n")

        analyst = RepoAnalyst(workspace_root=str(tmp_path))
        result = await analyst.run("Find all Python files")

        assert result.success
        assert "Repository structure" in result.output
        assert "Python files" in result.output
        assert len(result.tool_calls) >= 1  # Should have called list_files at minimum

    @pytest.mark.asyncio
    async def test_analyst_finds_todos(self, tmp_path: Path):
        (tmp_path / "code.py").write_text("# TODO: fix this\nx = 1\n# FIXME: broken\n")

        analyst = RepoAnalyst(workspace_root=str(tmp_path))
        result = await analyst.run("Find issues")

        assert result.success
        # Should have found the TODO/FIXME markers
        has_search = any(tc.get("tool") == "search_code" for tc in result.tool_calls)
        assert has_search

    @pytest.mark.asyncio
    async def test_analyst_checks_git(self, tmp_path: Path):
        analyst = RepoAnalyst(workspace_root=str(tmp_path))
        result = await analyst.run("Check changes")
        assert result.success
        # git_diff tool should have been called
        has_diff = any(tc.get("tool") == "git_diff" for tc in result.tool_calls)
        assert has_diff

    def test_analyst_tools_are_read_only(self):
        analyst = RepoAnalyst(workspace_root="/tmp")
        assert "write_patch" not in analyst.allowed_tools
        assert "run_tests" not in analyst.allowed_tools
        assert "list_files" in analyst.allowed_tools
        assert "search_code" in analyst.allowed_tools
        assert "read_file" in analyst.allowed_tools


# ── Implementer ────────────────────────────────────────────

class TestImplementer:
    @pytest.mark.asyncio
    async def test_implementer_describes_changes(self, tmp_path: Path):
        (tmp_path / "target.py").write_text("def old(): pass\n")

        impl = Implementer(workspace_root=str(tmp_path))
        result = await impl.run("Change old() to new() in target.py")

        assert result.success
        assert "Proposed Changes" in result.output
        assert "ORCHESTRATOR APPROVAL" in result.output

    @pytest.mark.asyncio
    async def test_implementer_reads_mentioned_files(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("x = 1\ny = 2\nz = 3\n")

        impl = Implementer(workspace_root=str(tmp_path))
        result = await impl.run("Optimize main.py")

        assert result.success
        read_calls = [tc for tc in result.tool_calls if tc.get("tool") == "read_file"]
        assert len(read_calls) >= 1

    def test_implementer_can_write_but_gated(self):
        impl = Implementer(workspace_root="/tmp")
        assert "write_patch" in impl.allowed_tools
        # The implementer CAN propose writes, but the Orchestrator gates them
        assert "read_file" in impl.allowed_tools

    def test_implementer_cannot_run_tests(self):
        impl = Implementer(workspace_root="/tmp")
        assert "run_tests" not in impl.allowed_tools


# ── Reviewer ───────────────────────────────────────────────

class TestReviewer:
    @pytest.mark.asyncio
    async def test_reviewer_checks_diff_and_tests(self, tmp_path: Path):
        (tmp_path / "test_sample.py").write_text("def test_ok(): assert True\n")

        reviewer = Reviewer(workspace_root=str(tmp_path))
        result = await reviewer.run("Review the changes to test_sample.py")

        assert result.success
        # Should have run git_diff and run_tests
        tools_called = {tc.get("tool") for tc in result.tool_calls}
        assert "git_diff" in tools_called
        assert "run_tests" in tools_called

    def test_reviewer_cannot_write(self):
        reviewer = Reviewer(workspace_root="/tmp")
        assert "write_patch" not in reviewer.allowed_tools
        assert "run_tests" in reviewer.allowed_tools
        assert "git_diff" in reviewer.allowed_tools


# ── Orchestrator ───────────────────────────────────────────

class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_full_workflow_completes(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("def main(): pass\n")
        (tmp_path / "test_main.py").write_text("def test_main(): assert True\n")

        orch = Orchestrator(workspace_root=str(tmp_path))
        result = await orch.run("Fix the bug in main.py")

        assert isinstance(result, OrchestratorResult)
        assert result.success
        assert len(result.phases) >= 3  # analyze, implement, review at minimum
        assert result.analyst_result is not None
        assert result.implementer_result is not None
        assert result.reviewer_result is not None
        assert len(result.final_summary) > 100

    @pytest.mark.asyncio
    async def test_orchestrator_phases_ordered(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("pass\n")

        orch = Orchestrator(workspace_root=str(tmp_path))
        result = await orch.run("Refactor main.py")

        phase_names = [p["phase"] for p in result.phases]
        assert phase_names[0] == "analyze"
        assert phase_names[1] == "implement"
        assert phase_names[2] == "review"

    @pytest.mark.asyncio
    async def test_approval_tracking(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("pass\n")

        orch = Orchestrator(
            workspace_root=str(tmp_path),
            auto_approve_risk=RiskLevel.LOW,
        )
        result = await orch.run("Add a new function")

        # Approvals should be tracked in the result
        assert isinstance(result.approvals, list)

    @pytest.mark.asyncio
    async def test_synthesis_includes_all_sections(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("pass\n")

        orch = Orchestrator(workspace_root=str(tmp_path))
        result = await orch.run("Optimize code")

        summary = result.final_summary
        assert "CodeSentry Report" in summary
        assert "Repository Analysis" in summary
        assert "Implementation" in summary
        assert "Review & Tests" in summary

    @pytest.mark.asyncio
    async def test_reports_duration(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("pass\n")

        orch = Orchestrator(workspace_root=str(tmp_path))
        result = await orch.run("Simple task")

        assert result.total_duration_ms > 0


# ── Orchestrator → Graph Integration ───────────────────────

class TestOrchestratorIntegration:
    @pytest.mark.asyncio
    async def test_run_orchestrator_agent(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("def main(): pass\n")

        from app.agents.graph import run_orchestrator_agent

        result = await run_orchestrator_agent(
            task="Analyze the code",
            workspace_root=str(tmp_path),
        )

        assert result["success"] is True
        assert len(result["phases"]) >= 3
        assert len(result["final_summary"]) > 0
        assert "duration_ms" in result

    @pytest.mark.asyncio
    async def test_orchestrator_respects_approval_level(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("pass\n")

        from app.agents.graph import run_orchestrator_agent

        result_low = await run_orchestrator_agent(
            task="Fix bug",
            workspace_root=str(tmp_path),
            auto_approve_risk="low",
        )
        assert result_low["success"]


# ── Sub-agent tool isolation ───────────────────────────────

class TestToolIsolation:
    """Verify sub-agents don't have access to tools beyond their role."""

    def test_analyst_cannot_write_or_execute(self):
        analyst = RepoAnalyst("/tmp")
        assert "write_patch" not in analyst.allowed_tools
        assert "run_tests" not in analyst.allowed_tools

    def test_implementer_cannot_run_tests(self):
        impl = Implementer("/tmp")
        assert "run_tests" not in impl.allowed_tools
        assert "git_diff" not in impl.allowed_tools

    def test_reviewer_cannot_write(self):
        reviewer = Reviewer("/tmp")
        assert "write_patch" not in reviewer.allowed_tools
        assert "list_files" not in reviewer.allowed_tools

    def test_no_agent_has_all_tools(self):
        """No single sub-agent should have access to all 6 tools."""
        agents = [
            RepoAnalyst("/tmp"),
            Implementer("/tmp"),
            Reviewer("/tmp"),
        ]
        for agent in agents:
            assert len(agent.allowed_tools) < 6, (
                f"{agent.name} has too many tools: {agent.allowed_tools}"
            )

    def test_orchestrator_controls_approvals(self):
        """Only the Orchestrator manages approval flow."""
        from app.security.permissions import ApprovalRequest

        # Verify the approval mechanism exists and is accessible
        req = ApprovalRequest(
            id="test-001",
            tool_name="write_patch",
            arguments={"file_path": "x.py", "content": "y"},
            risk_level=RiskLevel.HIGH,
            reason="Test",
        )
        assert req.risk_level == RiskLevel.HIGH
        assert req.tool_name == "write_patch"
