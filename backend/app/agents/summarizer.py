"""Summarizer node — produces the final report."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.prompts import SUMMARIZER_SYSTEM_PROMPT
from app.models.provider import get_model

logger = logging.getLogger(__name__)


def _build_fallback_summary(state: dict[str, Any]) -> str:
    """Deterministic summary without LLM."""
    plan = state.get("plan", [])
    tool_results = state.get("tool_results", [])
    observations = state.get("observations", [])

    lines = [
        "## Changes Made",
        "",
    ]

    completed = []
    failed = []
    for s in plan:
        if isinstance(s, dict):
            name = s.get("description", s.get("id", "?"))
            status = s.get("status", "unknown")
            summary = s.get("result_summary", "")
        else:
            name = s.description
            status = s.status
            summary = s.result_summary
        entry = f"- [{status.upper()}] {name}"
        if summary:
            entry += f" — {summary[:120]}"
        if status == "completed":
            completed.append(entry)
        else:
            failed.append(entry)

    lines.extend(completed)
    if failed:
        lines.append("")
        lines.append("### Incomplete / Failed")
        lines.extend(failed)

    lines.extend([
        "",
        "## Test Results",
        "",
    ])

    test_results = [r for r in tool_results if r.get("tool") == "run_tests"]
    if test_results:
        for tr in test_results:
            data = tr.get("data", {})
            if isinstance(data, dict):
                exit_code = data.get("exit_code", "?")
                lines.append(f"- Exit code: {exit_code}")
                stdout = data.get("stdout", "")
                if stdout:
                    lines.append(f"```\n{stdout[:500]}\n```")
    else:
        lines.append("- No tests were executed.")

    lines.extend([
        "",
        "## Notes & Recommendations",
        "",
        f"- Total iterations: {state.get('iteration', 0)}",
        f"- Tool calls: {len(tool_results)}",
        f"- Observations recorded: {len(observations)}",
    ])

    if state.get("error"):
        lines.append(f"- Error encountered: {state['error']}")

    return "\n".join(lines)


async def summarizer_node(state: dict[str, Any]) -> dict[str, Any]:
    """Generate the final summary of the agent's work."""
    logger.info("SUMMARIZER | producing final report")

    task = state.get("task", "")
    plan = state.get("plan", [])
    tool_results = state.get("tool_results", [])
    observations = state.get("observations", [])
    iteration = state.get("iteration", 0)

    try:
        model = get_model()

        # Build context for the model
        steps_summary = []
        for s in plan:
            if isinstance(s, dict):
                steps_summary.append(
                    f"- [{s.get('status', '?')}] {s.get('description', '')} "
                    f"(tool: {s.get('tool_name', 'none')})"
                )
            else:
                steps_summary.append(
                    f"- [{s.status}] {s.description} (tool: {s.tool_name or 'none'})"
                )

        tool_summary = []
        for tr in tool_results[-10:]:
            tool_summary.append(
                f"- {tr.get('tool', '?')}: success={tr.get('success')} "
                f"({tr.get('duration_ms', 0):.0f}ms)"
            )

        prompt = (
            f"{SUMMARIZER_SYSTEM_PROMPT}\n\n"
            f"## Original Task\n{task}\n\n"
            f"## Execution Summary\n"
            f"Iterations: {iteration}\n\n"
            f"### Plan Steps\n" + "\n".join(steps_summary) + "\n\n"
            f"### Tool Executions\n" + "\n".join(tool_summary) + "\n\n"
            f"### Key Observations\n" + "\n".join(f"- {o}" for o in observations[-5:]) + "\n\n"
            f"Produce the final markdown report."
        )

        # ── Prompt Cache ──
        cached_response = None
        try:
            from app.models.cache import get_cached as cache_get, set_cached as cache_set
            cached_response = await cache_get("summarizer", prompt)
        except Exception:
            pass

        if cached_response:
            summary = cached_response
        else:
            import asyncio as _asyncio
            try:
                result = await _asyncio.wait_for(model.ainvoke(prompt), timeout=90)
            except _asyncio.TimeoutError:
                logger.warning("SUMMARIZER | LLM call timed out, using fallback")
                raise
            summary = result.content if hasattr(result, "content") else str(result)
            try:
                await cache_set("summarizer", prompt, summary)
            except Exception:
                pass

    except Exception as exc:
        logger.warning("LLM summarizer failed, using fallback: %s", exc)
        summary = _build_fallback_summary(state)

    state["final_summary"] = summary
    state["next_action"] = "finish"
    return state
