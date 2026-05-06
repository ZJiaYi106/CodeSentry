"""Reflector node — evaluates results, decides next action."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage

from app.agents.prompts import REFLECTOR_SYSTEM_PROMPT
from app.models.provider import get_model

logger = logging.getLogger(__name__)


def _rule_based_reflection(state: dict[str, Any]) -> str:
    """Simple rule-based fallback for when the LLM is unavailable."""
    plan = state.get("plan", [])
    idx = state.get("current_step_index", 0)
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 15)

    if iteration >= max_iter:
        return "finish"

    # If all steps are done, finish
    if idx >= len(plan):
        return "finish"

    # Check if the last step failed
    last_step = None
    if idx > 0 and idx <= len(plan):
        last_step = plan[idx - 1]

    if isinstance(last_step, dict):
        status = last_step.get("status", "completed")
    elif last_step is not None:
        status = last_step.status
    else:
        status = "completed"

    # If too many failures, finish
    failed_count = sum(
        1 for s in plan
        if (isinstance(s, dict) and s.get("status") == "failed")
        or (not isinstance(s, dict) and s.status == "failed")
    )
    if failed_count >= 3:
        return "finish"

    if status == "failed":
        return "replan"

    return "continue"


async def reflector_node(state: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the last observation and decide next_action.

    Sets state["next_action"] to "continue", "replan", or "finish".
    """
    observations = state.get("observations", [])
    plan = state.get("plan", [])
    idx = state.get("current_step_index", 0)
    iteration = state.get("iteration", 0)

    logger.info("REFLECTOR | iteration=%d step=%d/%d", iteration, idx, len(plan))

    next_action = "continue"

    try:
        model = get_model()
        last_obs = observations[-3:] if observations else ["No observations yet"]
        obs_text = "\n".join(last_obs)

        prompt = (
            f"{REFLECTOR_SYSTEM_PROMPT}\n\n"
            f"## Task Progress\n"
            f"- Iteration: {iteration}\n"
            f"- Steps completed: {idx}/{len(plan)}\n"
            f"- Plan steps: {json.dumps([s if isinstance(s, dict) else {'id': s.id, 'description': s.description, 'tool_name': s.tool_name, 'status': s.status} for s in plan], indent=2)}\n\n"
            f"## Recent Observations\n{obs_text}\n\n"
            f"Output JSON with action (continue/replan/finish) and reason."
        )

        # ── Prompt Cache ──
        cached_response = None
        try:
            from app.models.cache import get_cached as cache_get, set_cached as cache_set
            cached_response = await cache_get("reflector", prompt)
        except Exception:
            pass

        if cached_response:
            content = cached_response
        else:
            result = await model.ainvoke(prompt)
            content = result.content if hasattr(result, "content") else str(result)
            try:
                await cache_set("reflector", prompt, content)
            except Exception:
                pass

        # Extract JSON
        json_match = re.search(r"\{[^}]*\}", content, re.DOTALL)
        if json_match:
            decision = json.loads(json_match.group(0))
            action = decision.get("action", "continue")
            reason = decision.get("reason", "")
            logger.info("REFLECTOR | decision=%s reason=%s", action, reason)
            if action in ("continue", "replan", "finish"):
                next_action = action
        else:
            next_action = _rule_based_reflection(state)

    except Exception as exc:
        logger.warning("LLM reflector failed, using rule-based fallback: %s", exc)
        next_action = _rule_based_reflection(state)

    # Safety: don't loop forever
    if iteration >= state.get("max_iterations", 15):
        next_action = "finish"

    state["next_action"] = next_action
    return state
