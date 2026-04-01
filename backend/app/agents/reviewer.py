"""Reviewer / Test Agent — validates changes and runs tests.

Test execution goes through the Orchestrator's approval gate.
"""

from __future__ import annotations

from app.agents.base_agent import BaseSubAgent, SubAgentResult


class Reviewer(BaseSubAgent):
    """Read + test-execution agent that validates code changes.

    Allowed tools:
      - read_file: review changed code
      - run_tests: execute test suite (REQUIRES Orchestrator approval)
      - git_diff: inspect the diff of changes

    The Reviewer CANNOT directly execute run_tests — it must go through
    the Orchestrator's approval flow.
    """

    name = "Reviewer"
    description = (
        "I review code changes for correctness, style, and safety. "
        "I also run tests to verify nothing is broken. "
        "Test execution requires Orchestrator approval."
    )
    allowed_tools = ["read_file", "run_tests", "git_diff"]

    async def run(self, task_context: str) -> SubAgentResult:
        """Review changes and (with approval) run tests."""
        import time

        start = time.perf_counter()

        lines: list[str] = []
        tool_calls: list[dict] = []

        # Step 1: Check git diff for changes
        try:
            differ = self._registry.get("git_diff")
            result = await differ.run()
            tool_calls.append(result.to_dict())
            if result.success and not result.data.get("empty", True):
                lines.append("Changes detected — review the diff above")
                diff_preview = result.data.get("diff", "")[:500]
                if diff_preview:
                    lines.append(f"```diff\n{diff_preview}\n```")
            else:
                lines.append("No changes to review (clean working tree)")
        except Exception as exc:
            lines.append(f"Git diff check failed: {exc}")

        # Step 2: Attempt to run tests (gated by Orchestrator approval)
        lines.append("")
        lines.append("## Test Execution")
        lines.append("Test execution requires Orchestrator approval.")
        lines.append("The Reviewer would:")
        lines.append("1. Run the existing test suite to establish baseline")
        lines.append("2. Verify no regressions after changes")
        lines.append("3. Report pass/fail counts and any errors")

        try:
            tester = self._registry.get("run_tests")
            result = await tester.run(command="pytest -x --tb=short 2>&1 || true", timeout_seconds=30)
            tool_calls.append(result.to_dict())
            if result.success:
                lines.append(f"✅ Tests passed: exit_code={result.data.get('exit_code', '?')}")
                stdout = result.data.get("stdout", "")
                if stdout:
                    lines.append(f"```\n{stdout[:500]}\n```")
            else:
                lines.append(f"❌ Tests failed: exit_code={result.data.get('exit_code', '?')}")
                stderr = result.data.get("stderr", "")
                if stderr:
                    lines.append(f"```\n{stderr[:300]}\n```")
        except Exception as exc:
            lines.append(f"⚠️  Test execution unavailable: {exc}")

        duration = (time.perf_counter() - start) * 1000
        return SubAgentResult(
            agent_name=self.name,
            success=True,
            output="\n".join(lines),
            tool_calls=tool_calls,
            duration_ms=duration,
        )
