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

    Safety guards:
      - Consecutive replans are capped at 3 — forces finish after that.
      - Consecutive tool failures are capped at 3 — forces finish after that.
      - Max iterations are enforced at the router level, but we also
        force finish here as a double safety net.
    """
    observations = state.get("observations", [])
    plan = state.get("plan", [])
    idx = state.get("current_step_index", 0)
    iteration = state.get("iteration", 0)

    logger.info("REFLECTOR | iteration=%d step=%d/%d", iteration, idx, len(plan))

    # ── Safety counters (persisted in state) ──────────────────
    consecutive_replans: int = state.get("_consecutive_replans", 0)
    consecutive_failures: int = state.get("_consecutive_failures", 0)

    # ── Safety: hard limits before even calling the LLM ───────
    if iteration >= state.get("max_iterations", 15):
        logger.warning("REFLECTOR | max iterations reached, forcing finish")
        state["next_action"] = "finish"
        return state

    if consecutive_replans >= 3:
        logger.warning("REFLECTOR | %d consecutive replans, forcing finish", consecutive_replans)
        state["next_action"] = "finish"
        return state

    if consecutive_failures >= 3:
        logger.warning("REFLECTOR | %d consecutive failures, forcing finish", consecutive_failures)
        state["next_action"] = "finish"
        return state

    # All plan steps completed successfully — finish
    if idx >= len(plan) and len(plan) > 0:
        has_failures = any(
            (isinstance(s, dict) and s.get("status") == "failed")
            or (not isinstance(s, dict) and getattr(s, "status", "") == "failed")
            for s in plan
        )
        if not has_failures:
            logger.info("REFLECTOR | all steps completed, finishing")
            state["next_action"] = "finish"
            state["_consecutive_replans"] = 0
            return state

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
            f"CRITICAL: If the agent has already completed all meaningful work or has been repeating the same actions, you MUST respond with 'finish'.\n"
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
            import asyncio as _asyncio
            try:
                result = await _asyncio.wait_for(model.ainvoke(prompt), timeout=90)
            except _asyncio.TimeoutError:
                logger.warning("REFLECTOR | LLM call timed out, using rule-based fallback")
                raise
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

    # ── Update safety counters ────────────────────────────────
    if next_action == "replan":
        state["_consecutive_replans"] = consecutive_replans + 1
    else:
        state["_consecutive_replans"] = 0

    # Check last step for failures
    last_step_failed = False
    if idx > 0 and idx <= len(plan):
        last_step = plan[idx - 1]
        if isinstance(last_step, dict):
            last_step_failed = last_step.get("status") == "failed"
        else:
            last_step_failed = getattr(last_step, "status", "") == "failed"

    if last_step_failed:
        state["_consecutive_failures"] = consecutive_failures + 1
    else:
        state["_consecutive_failures"] = 0

    # ── Final safety: refuse to loop forever ──────────────────
    if state["_consecutive_replans"] >= 3:
        logger.warning("REFLECTOR | replan limit reached after decision, forcing finish")
        next_action = "finish"

    if state["_consecutive_failures"] >= 3:
        logger.warning("REFLECTOR | failure limit reached, forcing finish")
        next_action = "finish"

    if iteration >= state.get("max_iterations", 15):
        next_action = "finish"

    state["next_action"] = next_action
    return state
