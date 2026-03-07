"""Tests for all six tools + tool registry."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.tools.base import BaseTool, RiskLevel, ToolParameter, ToolResult
from app.tools.code_search import SearchCodeTool
from app.tools.file_list import ListFilesTool
from app.tools.git_diff import GitDiffTool
from app.tools.read_file import ReadFileTool
from app.tools.registry import ToolRegistry
from app.tools.run_tests import RunTestsTool
from app.tools.write_patch import WritePatchTool


@pytest.fixture
def workspace(tmp_path: Path) -> str:
    return str(tmp_path)


# ── Tool Registry ──────────────────────────────────────────

class TestToolRegistry:
    def test_registers_six_tools(self, workspace):
        reg = ToolRegistry(workspace)
        names = {t.name for t in reg.list_tools()}
        assert names == {"list_files", "search_code", "read_file", "write_patch", "run_tests", "git_diff"}

    def test_get_existing_tool(self, workspace):
        reg = ToolRegistry(workspace)
        tool = reg.get("read_file")
        assert isinstance(tool, ReadFileTool)

    def test_get_missing_tool_raises(self, workspace):
        reg = ToolRegistry(workspace)
        with pytest.raises(KeyError):
            reg.get("nonexistent")

    def test_contains(self, workspace):
        reg = ToolRegistry(workspace)
        assert "list_files" in reg
        assert "nope" not in reg

    def test_to_openai_functions(self, workspace):
        reg = ToolRegistry(workspace)
        funcs = reg.to_openai_functions()
        assert len(funcs) == 6
        for f in funcs:
            assert f["type"] == "function"
            assert "name" in f["function"]


# ── ListFilesTool ──────────────────────────────────────────

class TestListFilesTool:
    @pytest.mark.asyncio
    async def test_lists_files_in_directory(self, workspace):
        (Path(workspace) / "a.py").write_text("x")
        (Path(workspace) / "b.py").write_text("y")
        (Path(workspace) / "sub").mkdir()
        (Path(workspace) / "sub" / "c.py").write_text("z")

        tool = ListFilesTool(workspace)
        result = await tool.run(path=".")
        assert result.success
        assert result.data["count"] == 3  # a.py, b.py, sub
        names = [os.path.normpath(e["path"]) for e in result.data["entries"]]
        assert os.path.normpath("a.py") in names
        assert os.path.normpath("sub") in names

    @pytest.mark.asyncio
    async def test_skips_hidden_files(self, workspace):
        (Path(workspace) / ".hidden").write_text("secret")
        (Path(workspace) / "visible.txt").write_text("hello")

        tool = ListFilesTool(workspace)
        result = await tool.run(path=".")
        assert result.success
        names = [os.path.normpath(e["path"]) for e in result.data["entries"]]
        assert os.path.normpath("visible.txt") in names
        assert os.path.normpath(".hidden") not in names

    @pytest.mark.asyncio
    async def test_recursive_listing(self, workspace):
        (Path(workspace) / "sub").mkdir()
        (Path(workspace) / "sub" / "d.py").write_text("d")
        (Path(workspace) / "root.txt").write_text("r")

        tool = ListFilesTool(workspace)
        result = await tool.run(path=".", recursive=True)
        assert result.success
        paths = {os.path.normpath(e["path"]) for e in result.data["entries"]}
        assert os.path.normpath("root.txt") in paths
        assert os.path.normpath("sub/d.py") in paths

    @pytest.mark.asyncio
    async def test_missing_path(self, workspace):
        tool = ListFilesTool(workspace)
        result = await tool.run(path="nope")
        assert not result.success


# ── SearchCodeTool ─────────────────────────────────────────

class TestSearchCodeTool:
    @pytest.mark.asyncio
    async def test_finds_pattern(self, workspace):
        (Path(workspace) / "hello.py").write_text("def foo():\n    return 42\n")

        tool = SearchCodeTool(workspace)
        result = await tool.run(pattern=r"def foo", path=".")
        assert result.success
        assert result.data["match_count"] >= 1
        assert any("hello.py" in r["file"] for r in result.data["results"])

    @pytest.mark.asyncio
    async def test_no_match(self, workspace):
        (Path(workspace) / "a.py").write_text("x = 1\n")

        tool = SearchCodeTool(workspace)
        result = await tool.run(pattern=r"nonexistent_function", path=".")
        assert result.success
        assert result.data["match_count"] == 0

    @pytest.mark.asyncio
    async def test_invalid_regex(self, workspace):
        tool = SearchCodeTool(workspace)
        result = await tool.run(pattern=r"[invalid", path=".")
        assert not result.success

    @pytest.mark.asyncio
    async def test_skips_non_code_files(self, workspace):
        (Path(workspace) / "image.png").write_text("not really png")  # txt but wrong ext

        tool = SearchCodeTool(workspace)
        result = await tool.run(pattern=r"really", path=".")
        assert result.success
        assert result.data["match_count"] == 0

    @pytest.mark.asyncio
    async def test_respects_file_pattern(self, workspace):
        (Path(workspace) / "a.py").write_text("TODO")
        (Path(workspace) / "b.js").write_text("TODO")

        tool = SearchCodeTool(workspace)
        result = await tool.run(pattern="TODO", path=".", file_pattern="*.js")
        assert result.success
        files = [r["file"] for r in result.data["results"]]
        assert all(f.endswith(".js") for f in files)


# ── ReadFileTool ───────────────────────────────────────────

class TestReadFileTool:
    @pytest.mark.asyncio
    async def test_reads_entire_file(self, workspace):
        (Path(workspace) / "data.txt").write_text("line1\nline2\nline3\n")

        tool = ReadFileTool(workspace)
        result = await tool.run(file_path="data.txt")
        assert result.success
        assert result.data["total_lines"] == 3
        assert "line1" in result.data["content"]

    @pytest.mark.asyncio
    async def test_reads_with_offset_limit(self, workspace):
        (Path(workspace) / "nums.txt").write_text("1\n2\n3\n4\n5\n")

        tool = ReadFileTool(workspace)
        result = await tool.run(file_path="nums.txt", offset=2, limit=2)
        assert result.success
        content = result.data["content"]
        assert "2" in content
        assert "3" in content
        assert "1" not in content

    @pytest.mark.asyncio
    async def test_file_not_found(self, workspace):
        tool = ReadFileTool(workspace)
        result = await tool.run(file_path="ghost.txt")
        assert not result.success

    @pytest.mark.asyncio
    async def test_directory_not_a_file(self, workspace):
        (Path(workspace) / "mydir").mkdir()
        tool = ReadFileTool(workspace)
        result = await tool.run(file_path="mydir")
        assert not result.success


# ── WritePatchTool ─────────────────────────────────────────

class TestWritePatchTool:
    @pytest.mark.asyncio
    async def test_writes_new_file(self, workspace):
        tool = WritePatchTool(workspace)
        result = await tool.run(file_path="new.txt", content="hello world")
        assert result.success
        assert (Path(workspace) / "new.txt").read_text() == "hello world"
        assert result.data["existed_before"] is False

    @pytest.mark.asyncio
    async def test_overwrites_existing_with_backup(self, workspace):
        f = Path(workspace) / "existing.txt"
        f.write_text("original")

        tool = WritePatchTool(workspace)
        result = await tool.run(file_path="existing.txt", content="modified", create_backup=True)
        assert result.success
        assert f.read_text() == "modified"
        assert (Path(workspace) / "existing.txt.bak").read_text() == "original"

    @pytest.mark.asyncio
    async def test_creates_parent_directories(self, workspace):
        tool = WritePatchTool(workspace)
        result = await tool.run(file_path="deep/nested/file.txt", content="deep")
        assert result.success
        assert (Path(workspace) / "deep" / "nested" / "file.txt").read_text() == "deep"


# ── RunTestsTool ───────────────────────────────────────────

class TestRunTestsTool:
    @pytest.mark.asyncio
    async def test_runs_pytest(self, workspace):
        (Path(workspace) / "test_sample.py").write_text(
            "def test_pass(): assert 1 + 1 == 2\n"
        )
        tool = RunTestsTool(workspace)
        result = await tool.run(command="pytest test_sample.py -v", timeout_seconds=30)
        assert result.success
        assert "passed" in result.data.get("stdout", "").lower() or result.data["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_rejects_unlisted_command(self, workspace):
        tool = RunTestsTool(workspace)
        result = await tool.run(command="rm -rf /", timeout_seconds=5)
        assert not result.success
        assert "not in the allowed" in (result.error or "")

    @pytest.mark.asyncio
    async def test_captures_failure(self, workspace):
        (Path(workspace) / "test_fail.py").write_text(
            "def test_fail(): assert 1 == 2\n"
        )
        tool = RunTestsTool(workspace)
        result = await tool.run(command="pytest test_fail.py", timeout_seconds=30)
        # The tool itself succeeded in execution, but tests failed
        assert result.success is not None  # result exists
        assert result.data["exit_code"] != 0


# ── GitDiffTool ────────────────────────────────────────────

class TestGitDiffTool:
    @pytest.mark.asyncio
    async def test_no_git_repo_returns_error(self, workspace):
        tool = GitDiffTool(workspace)
        result = await tool.run()
        # Either fails (not a repo) or git not installed — both are acceptable
        assert not result.success or result.data.get("empty", True)


# ── Path Traversal Prevention ──────────────────────────────

class TestPathTraversalPrevention:
    @pytest.mark.asyncio
    async def test_blocks_parent_traversal(self, tmp_path: Path):
        ws = tmp_path / "safe"
        ws.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")

        tool = ReadFileTool(str(ws))
        result = await tool.run(file_path="../outside.txt")
        assert not result.success
        assert "traversal" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_blocks_absolute_outside_path(self, tmp_path: Path):
        ws = tmp_path / "safe"
        ws.mkdir()

        tool = ReadFileTool(str(ws))
        result = await tool.run(file_path="/etc/passwd")
        assert not result.success

    @pytest.mark.asyncio
    async def test_blocks_write_outside_workspace(self, tmp_path: Path):
        ws = tmp_path / "safe"
        ws.mkdir()
        outside = tmp_path / "outside.txt"

        tool = WritePatchTool(str(ws))
        result = await tool.run(file_path="../outside.txt", content="evil")
        assert not result.success


# ── Risk Level Assignment ──────────────────────────────────

class TestRiskLevels:
    def test_low_risk_tools(self, workspace):
        for name in ("list_files", "search_code", "read_file", "git_diff"):
            tool = ToolRegistry(workspace).get(name)
            assert tool.risk_level == RiskLevel.LOW, f"{name} should be LOW risk"

    def test_medium_risk_tools(self, workspace):
        tool = ToolRegistry(workspace).get("run_tests")
        assert tool.risk_level == RiskLevel.MEDIUM

    def test_high_risk_tools(self, workspace):
        tool = ToolRegistry(workspace).get("write_patch")
        assert tool.risk_level == RiskLevel.HIGH
