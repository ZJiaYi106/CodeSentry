"""Planner node — analyzes task, generates execution plan with tool bindings."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.agents.prompts import PLANNER_SYSTEM_PROMPT
from app.models.provider import get_model

logger = logging.getLogger(__name__)

# Simple fallback plan patterns for when the LLM is unavailable
# or for deterministic testing


def _pattern_based_plan(task: str) -> list[dict[str, Any]]:
    """Generate a plan without calling the LLM — used as fallback."""
    steps: list[dict[str, Any]] = []
    task_lower = task.lower()

    # Step 1: Always explore the repo
    steps.append({
        "id": "step_1",
        "description": "Explore the repository structure",
        "tool_name": "list_files",
        "tool_args": {"path": ".", "recursive": False},
    })

    # Step 2: Search for relevant code
    if "fix" in task_lower or "bug" in task_lower:
        steps.append({
            "id": "step_2",
            "description": "Search for potential bug locations",
            "tool_name": "search_code",
            "tool_args": {"pattern": "TODO|FIXME|bug|error", "path": "."},
        })
    elif "add" in task_lower or "implement" in task_lower:
        steps.append({
            "id": "step_2",
            "description": "Search for related code patterns",
            "tool_name": "search_code",
            "tool_args": {"pattern": "def |class ", "path": "."},
        })
    else:
        steps.append({
            "id": "step_2",
            "description": "Inspect relevant source files",
            "tool_name": "search_code",
            "tool_args": {"pattern": ".", "path": ".", "file_pattern": "*.py"},
        })

    # Step 3: Read key files
    steps.append({
        "id": "step_3",
        "description": "Read key source files to understand context",
        "tool_name": "read_file",
        "tool_args": {"file_path": "README.md", "offset": 1, "limit": 50},
    })

    # Step 4: Run existing tests
    steps.append({
        "id": "step_4",
        "description": "Run existing tests to establish baseline",
        "tool_name": "run_tests",
        "tool_args": {"command": "pytest -x --tb=short", "timeout_seconds": 60},
    })

    return steps


async def planner_node(state: dict[str, Any]) -> dict[str, Any]:
    """Analyze the task and produce a list of execution steps.

    Uses the LLM to generate a structured JSON plan.  Falls back to
    pattern-based planning if the LLM is unavailable.

    Before planning, searches long-term memory for relevant past experiences
    and injects them into the prompt context.
    """
    task = state.get("task", "")
    iteration = state.get("iteration", 0)
    previous_observations = state.get("observations", [])

    logger.info("PLANNER | task='%s...' iteration=%d", task[:80], iteration)

    # ── Retrieve long-term memory ──────────────────────────
    memory_context = ""
    try:
        from app.memory.long_term import search_memories

        # Search across all three collections
        fix_results = await search_memories(task, "fix_patterns", n_results=2)
        convention_results = await search_memories(task, "project_conventions", n_results=2)
        pref_results = await search_memories(task, "user_preferences", n_results=1)

        if fix_results or convention_results or pref_results:
            memory_context = "\n## Relevant Past Experience (from long-term memory)\n"
            if fix_results:
                memory_context += "### Similar fixes from past tasks:\n"
                for r in fix_results:
                    memory_context += f"- {r['content'][:300]}\n"
            if convention_results:
                memory_context += "### Project conventions:\n"
                for r in convention_results:
                    memory_context += f"- {r['content'][:300]}\n"
            if pref_results:
                memory_context += "### User preferences:\n"
                for r in pref_results:
                    memory_context += f"- {r['content'][:300]}\n"
            logger.info("PLANNER | injected %d memory results", len(fix_results) + len(convention_results) + len(pref_results))
    except Exception as exc:
        logger.debug("PLANNER | memory search skipped: %s", exc)

    plan_steps: list[dict[str, Any]] = []

    try:
        model = get_model()

        obs_context = ""
        if previous_observations:
            obs_context = "\nRecent observations:\n" + "\n".join(
                previous_observations[-5:]
            )

        prompt = (
            f"{PLANNER_SYSTEM_PROMPT}\n\n"
            f"{memory_context}"
            f"## User Task\n{task}\n{obs_context}\n\n"
            f"## Available Tools\n"
            f"- list_files: List directory contents (risk: low)\n"
            f"- search_code: Search code with regex patterns (risk: low)\n"
            f"- read_file: Read file contents (risk: low)\n"
            f"- write_patch: Write/modify a file (risk: HIGH, requires approval)\n"
            f"- run_tests: Run test commands (risk: medium, requires approval)\n"
            f"- git_diff: View git changes (risk: low)\n\n"
            f"## Instructions\n"
            f"Generate a JSON array of plan steps. Each step must have:\n"
            f'  "id": unique string\n'
            f'  "description": what this step does\n'
            f'  "tool_name": one of the tools above, or null for reasoning\n'
            f'  "tool_args": dict of tool parameters, or empty dict\n'
            f"Output ONLY the JSON array, no other text."
        )

        result = await model.ainvoke(prompt)
        content = result.content if hasattr(result, "content") else str(result)

        # Extract JSON from the response
        json_match = re.search(r"\[.*\]", content, re.DOTALL)
        if json_match:
            plan_steps = json.loads(json_match.group(0))
        else:
            logger.warning("Could not extract JSON from planner response, using fallback")
            plan_steps = _pattern_based_plan(task)

    except Exception as exc:
        logger.warning("LLM planner failed, using pattern-based fallback: %s", exc)
        plan_steps = _pattern_based_plan(task)

    # Ensure each step has the required fields
    for i, step in enumerate(plan_steps):
        step.setdefault("id", f"step_{i+1}")
        step.setdefault("status", "pending")
        step.setdefault("tool_args", {})
        step.setdefault("result_summary", "")

    # If no plan was generated, use fallback
    if not plan_steps:
        plan_steps = _pattern_based_plan(task)

    state["plan"] = plan_steps
    state["current_step_index"] = 0
    state["iteration"] = iteration + 1

    logger.info("PLANNER | generated %d steps: %s", len(plan_steps),
                 [s.get("tool_name") or "reasoning" for s in plan_steps])

    return state
