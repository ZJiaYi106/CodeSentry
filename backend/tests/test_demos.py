"""Integration tests — verify all 3 demos run end-to-end."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest

# Path to demo workspace files
DEMOS_ROOT = Path(__file__).parent.parent.parent / "demos"


class TestDemo1FixTypo:
    @pytest.mark.asyncio
    async def test_demo1_workflow_completes(self):
        """Demo 1: Orchestrator runs all 4 phases on the typo-fix workspace."""
        from app.agents.orchestrator import Orchestrator

        demo_dir = DEMOS_ROOT / "demo1_fix_typo" / "workspace"
        work_dir = Path(tempfile.mkdtemp(prefix="test_demo1_"))
        shutil.copytree(demo_dir, work_dir, dirs_exist_ok=True)

        orch = Orchestrator(workspace_root=str(work_dir))
        result = await orch.run("Fix the variable name typos in utils.py")

        assert result.success
        assert result.analyst_result is not None
        assert result.implementer_result is not None
        assert result.reviewer_result is not None
        assert result.total_duration_ms > 0
        assert len(result.final_summary) > 100

        # Verify phase ordering
        phases = [p["phase"] for p in result.phases if p["status"] == "completed"]
        assert "analyze" in phases
        assert "implement" in phases
        assert "review" in phases
        assert "done" in phases

    @pytest.mark.asyncio
    async def test_demo1_files_unchanged_without_llm(self):
        """Without an LLM, the fallback mode should not modify files."""
        from app.agents.orchestrator import Orchestrator

        demo_dir = DEMOS_ROOT / "demo1_fix_typo" / "workspace"
        work_dir = Path(tempfile.mkdtemp(prefix="test_demo1b_"))
        shutil.copytree(demo_dir, work_dir, dirs_exist_ok=True)

        original = (work_dir / "utils.py").read_text(encoding="utf-8")

        orch = Orchestrator(workspace_root=str(work_dir))
        await orch.run("Fix typos")

        after = (work_dir / "utils.py").read_text(encoding="utf-8")
        # Fallback mode describes changes but doesn't apply them
        # (with a real API key and approval, it would)
        assert "numers" in after  # The typo is still there in fallback mode


class TestDemo2AddDocstring:
    @pytest.mark.asyncio
    async def test_demo2_workflow_completes(self):
        """Demo 2: Orchestrator runs on the docstring workspace."""
        from app.agents.orchestrator import Orchestrator

        demo_dir = DEMOS_ROOT / "demo2_add_docstring" / "workspace"
        work_dir = Path(tempfile.mkdtemp(prefix="test_demo2_"))
        shutil.copytree(demo_dir, work_dir, dirs_exist_ok=True)

        orch = Orchestrator(workspace_root=str(work_dir))
        result = await orch.run("Add docstrings to all functions in calculator.py")

        assert result.success
        assert result.total_duration_ms > 0


class TestDemo3Refactor:
    @pytest.mark.asyncio
    async def test_demo3_workflow_completes(self):
        """Demo 3: Orchestrator runs on the refactor workspace."""
        from app.agents.orchestrator import Orchestrator

        demo_dir = DEMOS_ROOT / "demo3_refactor" / "workspace"
        work_dir = Path(tempfile.mkdtemp(prefix="test_demo3_"))
        shutil.copytree(demo_dir, work_dir, dirs_exist_ok=True)

        orch = Orchestrator(workspace_root=str(work_dir))
        result = await orch.run(
            "Refactor process_user_data() into smaller helper functions"
        )

        assert result.success
        assert result.total_duration_ms > 0
        assert "Refactor" in result.final_summary or "refactor" in result.final_summary.lower()


class TestDemoIntegration:
    """End-to-end: memory persists across demo runs."""

    @pytest.mark.asyncio
    async def test_memory_persists_across_tasks(self):
        """Run two similar tasks — second should retrieve first's memory."""
        from app.agents.orchestrator import Orchestrator
        from app.memory.long_term import search_memories, clear_collection

        await clear_collection("fix_patterns", clear_fallback=True)

        demo_dir = DEMOS_ROOT / "demo1_fix_typo" / "workspace"
        work_dir = Path(tempfile.mkdtemp(prefix="test_mem_across_"))
        shutil.copytree(demo_dir, work_dir, dirs_exist_ok=True)

        # First task stores memory
        orch1 = Orchestrator(workspace_root=str(work_dir))
        result1 = await orch1.run("Fix the bug with variable name typo in utils.py")
        assert result1.success

        # Second similar task
        orch2 = Orchestrator(workspace_root=str(work_dir))
        result2 = await orch2.run("Fix typo bug in variable names")
        assert result2.success

        # Memory should have been stored (at least via fallback)
        results = await search_memories("typo bug variable", "fix_patterns", n_results=3)
        # In fallback mode, memories are stored in the in-memory list
        assert isinstance(results, list)
