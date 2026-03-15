"""Tests for memory system — short-term state and context compression."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.memory.compressor import compress_if_needed, estimate_tokens
from app.memory.short_term import AgentState, NextAction, PlanStep


class TestAgentStateDataclass:
    def test_defaults(self):
        state = AgentState(task="test", workspace_root="/ws")
        assert state.iteration == 0
        assert state.next_action == NextAction.CONTINUE.value
        assert state.plan == []
        assert state.error is None

    def test_current_step_none_when_empty(self):
        state = AgentState(task="test", workspace_root="/ws")
        assert state.current_step is None

    def test_current_step_returns_active(self):
        step = PlanStep(id="s1", description="do something")
        state = AgentState(task="test", workspace_root="/ws", plan=[step])
        assert state.current_step is step

    def test_is_done_on_finish(self):
        state = AgentState(task="test", workspace_root="/ws", next_action=NextAction.FINISH.value)
        assert state.is_done

    def test_is_done_on_max_iterations(self):
        state = AgentState(task="test", workspace_root="/ws", iteration=15, max_iterations=15)
        assert state.is_done

    def test_add_observation_updates_step(self):
        step = PlanStep(id="s1", description="do", tool_name="list_files")
        state = AgentState(task="test", workspace_root="/ws", plan=[step])
        state.add_observation("Found 5 files")
        assert len(state.observations) == 1
        assert step.result_summary == "Found 5 files"

    def test_add_tool_result(self):
        state = AgentState(task="test", workspace_root="/ws")
        state.add_tool_result({"tool": "read_file", "success": True})
        assert len(state.tool_results) == 1

    def test_to_dict(self):
        step = PlanStep(id="s1", description="do", tool_name="read_file", status="completed")
        state = AgentState(task="test task", workspace_root="/ws", plan=[step], iteration=3)
        d = state.to_dict()
        assert d["task"] == "test task"
        assert len(d["plan"]) == 1
        assert d["plan"][0]["status"] == "completed"


class TestCompressor:
    def test_estimate_tokens_empty(self):
        assert estimate_tokens([]) == 0

    def test_estimate_tokens_rough(self):
        msgs = [HumanMessage(content="hello " * 100)]  # 600 chars → ~150 tokens
        tokens = estimate_tokens(msgs)
        assert 100 <= tokens <= 200

    @pytest.mark.asyncio
    async def test_no_compression_below_threshold(self):
        msgs = [HumanMessage(content="short message")]
        result = await compress_if_needed(msgs, model=None, threshold_tokens=1000)
        assert result is msgs  # Same object — no compression needed

    @pytest.mark.asyncio
    async def test_compression_triggered_above_threshold(self):
        # Create 20 messages with enough content to exceed a low threshold
        msgs = []
        for i in range(20):
            msgs.append(HumanMessage(content=f"Message {i}: " + ("data " * 50)))
            msgs.append(AIMessage(content=f"Response {i}: " + ("info " * 50)))

        result = await compress_if_needed(msgs, model=None, threshold_tokens=50)
        # Should be compressed — fewer messages
        assert len(result) < len(msgs)
        # Should contain the compression header
        combined = " ".join(
            m.content if isinstance(m.content, str) else "" for m in result
        )
        assert "COMPRESSED" in combined

    @pytest.mark.asyncio
    async def test_preserves_system_messages(self):
        sys_msg = SystemMessage(content="System instruction")
        msgs = [sys_msg] + [
            HumanMessage(content=f"msg {i}: " + ("x " * 100))
            for i in range(20)
        ]
        result = await compress_if_needed(msgs, model=None, threshold_tokens=50)
        # System messages preserved at the top
        assert isinstance(result[0], SystemMessage)

    @pytest.mark.asyncio
    async def test_keeps_recent_messages(self):
        msgs = []
        for i in range(15):
            msgs.append(HumanMessage(content=f"old {i}: " + ("y " * 50)))
        msgs.append(HumanMessage(content="recent important message"))

        result = await compress_if_needed(msgs, model=None, threshold_tokens=100)
        # The last message should be preserved
        last_content = result[-1].content if isinstance(result[-1].content, str) else ""
        assert "recent important" in last_content
