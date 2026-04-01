"""Repository Analyst — read-only sub-agent for code exploration."""

from __future__ import annotations

from app.agents.base_agent import BaseSubAgent, SubAgentResult


class RepoAnalyst(BaseSubAgent):
    """Read-only agent that explores the repository structure and code.

    Allowed tools (read-only, low risk):
      - list_files: discover project structure
      - search_code: find relevant code patterns
      - read_file: understand implementation details
      - git_diff: see current changes
    """

    name = "Repository Analyst"
    description = (
        "I explore code repositories to understand their structure, "
        "identify relevant files, and gather context for the task at hand."
    )
    allowed_tools = ["list_files", "search_code", "read_file", "git_diff"]

    async def run(self, task_context: str) -> SubAgentResult:
        """Explore the repo and gather relevant context."""
        import time

        start = time.perf_counter()

        findings: list[str] = []
        tool_calls: list[dict] = []

        # Step 1: List top-level files
        try:
            lister = self._registry.get("list_files")
            result = await lister.run(path=".", recursive=False)
            tool_calls.append(result.to_dict())
            if result.success and result.data:
                entries = result.data.get("entries", [])
                py_files = [e for e in entries if e.get("type") == "file" and e["path"].endswith(".py")]
                dirs = [e for e in entries if e.get("type") == "dir"]
                findings.append(
                    f"Repository structure: {len(entries)} entries "
                    f"({len(py_files)} Python files, {len(dirs)} directories)"
                )
                for f in py_files[:5]:
                    findings.append(f"  Found: {f['path']}")
        except Exception as exc:
            findings.append(f"Error listing files: {exc}")

        # Step 2: Search for TODO/FIXME markers
        try:
            searcher = self._registry.get("search_code")
            result = await searcher.run(pattern=r"TODO|FIXME|HACK|XXX", path=".", max_results=10)
            tool_calls.append(result.to_dict())
            if result.success and result.data:
                count = result.data.get("match_count", 0)
                findings.append(f"Found {count} TODO/FIXME markers in codebase")
        except Exception as exc:
            findings.append(f"Error searching code: {exc}")

        # Step 3: Check git diff
        try:
            differ = self._registry.get("git_diff")
            result = await differ.run()
            tool_calls.append(result.to_dict())
            if result.success and result.data and not result.data.get("empty", True):
                findings.append("Uncommitted changes detected in repository")
            else:
                findings.append("No uncommitted changes (clean working tree or not a git repo)")
        except Exception as exc:
            findings.append(f"Error checking git diff: {exc}")

        duration = (time.perf_counter() - start) * 1000
        output = "\n".join(findings)

        return SubAgentResult(
            agent_name=self.name,
            success=True,
            output=output,
            tool_calls=tool_calls,
            duration_ms=duration,
        )
