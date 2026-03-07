"""Tests for audit logging."""

from __future__ import annotations

from app.audit.logger import get_recent_events, log_event, _in_memory_log


class TestAuditLogger:
    def setup_method(self):
        _in_memory_log.clear()

    def test_log_tool_call(self):
        event = log_event(
            event_type="tool_call",
            agent="orchestrator",
            tool_name="read_file",
            risk_level="low",
            parameters={"file_path": "test.py"},
            output_summary="3 lines read",
            duration_ms=12.5,
            success=True,
        )
        assert event["event_type"] == "tool_call"
        assert event["tool_name"] == "read_file"
        assert event["success"] == "true"
        assert event["duration_ms"] == 12.5

    def test_log_model_decision(self):
        event = log_event(
            event_type="model_decision",
            agent="planner",
            tool_name=None,
            risk_level=None,
            parameters={"decision": "run_tests"},
            output_summary="Planner decided to run tests",
        )
        assert event["event_type"] == "model_decision"

    def test_recent_events_limit(self):
        for i in range(10):
            log_event(event_type="tool_call", tool_name=f"tool_{i}")
        events = get_recent_events(limit=5)
        assert len(events) == 5

    def test_output_truncation(self):
        long_output = "x" * 1000
        event = log_event(event_type="tool_call", output_summary=long_output)
        assert len(event["output_summary"]) <= 500
