"""LangGraph StateGraph — the core agent Query Loop.

  START → planner → [tool calls?] → tool_executor → observation
       → reflector → [continue|replan|finish]
            replan → planner
            finish → summarizer → END

Each node mutates the shared AgentState dict.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.planner import planner_node
from app.agents.reflector import reflector_node
from app.agents.summarizer import summarizer_node
from app.memory.short_term import AgentState

logger = logging.getLogger(__name__)


# ── State Schema ───────────────────────────────────────────

def _initial_state(
    task: str,
    workspace_root: str,
    max_iterations: int = 15,
    messages: list | None = None,
) -> dict[str, Any]:
    return {
        "task": task,
        "workspace_root": workspace_root,
        "messages": messages or [],
        "plan": [],
        "current_step_index": 0,
        "observations": [],
        "tool_results": [],
        "iteration": 0,
        "max_iterations": max_iterations,
        "next_action": "continue",
        "final_summary": "",
        "error": None,
        "approval_required": False,
        "pending_approval_id": None,
    }


# ── Tool Execution Node ────────────────────────────────────

async def tool_executor_node(state: dict[str, Any]) -> dict[str, Any]:
    """Execute the tool for the current plan step.

    Reads state["plan"][state["current_step_index"]] and executes the tool.
    Appends result to state["tool_results"] and updates step status.
    """
    from app.tools.registry import ToolRegistry

    logger.info("TOOL EXECUTOR | iteration=%d", state.get("iteration", 0))

    plan = state.get("plan", [])
    idx = state.get("current_step_index", 0)

    if idx >= len(plan):
        return state

    step = plan[idx]
    tool_name = step.get("tool_name") if isinstance(step, dict) else step.tool_name

    if tool_name is None:
        # No tool — just a reasoning step, mark done and advance
        if isinstance(step, dict):
            step["status"] = "completed"
        else:
            step.status = "completed"
        state["current_step_index"] = idx + 1
        return state

    # Execute the tool
    workspace = state.get("workspace_root", "/workspace")
    registry = ToolRegistry(workspace)

    try:
        tool = registry.get(tool_name)
        args = step.get("tool_args", {}) if isinstance(step, dict) else step.tool_args
        result = await tool.run(**args)

        state["tool_results"].append(result.to_dict())

        if isinstance(step, dict):
            step["status"] = "completed" if result.success else "failed"
            step["result_summary"] = (result.data or result.error or "")[:300]
        else:
            step.status = "completed" if result.success else "failed"
            step.result_summary = (str(result.data) or result.error or "")[:300]

        # Add observation
        obs = f"[{tool_name}] success={result.success} | {step.get('result_summary', '') if isinstance(step, dict) else step.result_summary}"
        state["observations"].append(obs)

    except KeyError:
        state["error"] = f"Tool '{tool_name}' not found"
        if isinstance(step, dict):
            step["status"] = "failed"
            step["result_summary"] = f"Tool not found: {tool_name}"
        else:
            step.status = "failed"
            step.result_summary = f"Tool not found: {tool_name}"
    except Exception as exc:
        state["error"] = str(exc)
        if isinstance(step, dict):
            step["status"] = "failed"
            step["result_summary"] = str(exc)[:300]
        else:
            step.status = "failed"
            step.result_summary = str(exc)[:300]

    # Advance to next step
    state["current_step_index"] = idx + 1
    return state


# ── Observation Node ───────────────────────────────────────

async def observation_node(state: dict[str, Any]) -> dict[str, Any]:
    """Record observations and prepare for reflection.

    Collected from the last tool execution result.
    """
    logger.info("OBSERVATION | iteration=%d", state.get("iteration", 0))
    # In a full implementation this would parse tool output and extract insights.
    # Currently, tool_executor_node already records observations.
    return state


# ── Routing ────────────────────────────────────────────────

def _router_after_planner(state: dict[str, Any]) -> Literal["tool_executor", "summarizer"]:
    """After planning: if plan has tool steps → execute, else → summarize."""
    plan = state.get("plan", [])
    next_action = state.get("next_action", "continue")

    if next_action == "finish" or len(plan) == 0:
        return "summarizer"

    # Check if we still have pending steps
    idx = state.get("current_step_index", 0)
    if idx < len(plan):
        step = plan[idx]
        tool_name = step.get("tool_name") if isinstance(step, dict) else step.tool_name
        if tool_name:
            return "tool_executor"

    # No tool steps remaining
    return "summarizer"


def _router_after_reflector(state: dict[str, Any]) -> Literal["planner", "tool_executor", "summarizer"]:
    """After reflection: continue, replan, or finish."""
    next_action = state.get("next_action", "finish")
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 15)

    if next_action == "finish" or iteration >= max_iter:
        return "summarizer"
    if next_action == "replan":
        return "planner"

    # continue — check if there are more tool steps
    plan = state.get("plan", [])
    idx = state.get("current_step_index", 0)
    if idx < len(plan):
        return "tool_executor"
    return "summarizer"


# ── Build Graph ────────────────────────────────────────────

def build_agent_graph() -> CompiledStateGraph:
    """Build and compile the LangGraph StateGraph for the CodeSentry agent."""

    graph = StateGraph(dict)

    # Nodes
    graph.add_node("planner", planner_node)
    graph.add_node("tool_executor", tool_executor_node)
    graph.add_node("observation", observation_node)
    graph.add_node("reflector", reflector_node)
    graph.add_node("summarizer", summarizer_node)

    # Edges
    graph.set_entry_point("planner")

    graph.add_conditional_edges(
        "planner",
        _router_after_planner,
        {"tool_executor": "tool_executor", "summarizer": "summarizer"},
    )

    graph.add_edge("tool_executor", "observation")
    graph.add_edge("observation", "reflector")

    graph.add_conditional_edges(
        "reflector",
        _router_after_reflector,
        {
            "planner": "planner",
            "tool_executor": "tool_executor",
            "summarizer": "summarizer",
        },
    )

    graph.add_edge("summarizer", END)

    compiled = graph.compile()
    logger.info("Agent graph compiled successfully")
    return compiled


async def run_agent(
    task: str,
    workspace_root: str,
    max_iterations: int = 15,
) -> dict[str, Any]:
    """Run the full agent loop and return the final state.

    This is the main entry point for the backend API.
    """
    graph = build_agent_graph()
    initial = _initial_state(task, workspace_root, max_iterations)
    final_state = await graph.ainvoke(initial)
    return final_state
