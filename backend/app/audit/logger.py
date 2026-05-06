"""Audit log models and writer.

Records every model decision, tool call, parameter, output summary, duration,
and risk level for traceability and debugging.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base

logger = logging.getLogger("codesentry.audit")


# ── SQLAlchemy Model ──────────────────────────────────────

class AuditRecord(Base):
    """Persistent audit log entry."""

    __tablename__ = "audit_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    event_type = Column(String(64), nullable=False)  # tool_call | model_decision | approval | error
    agent = Column(String(64), nullable=True)
    tool_name = Column(String(64), nullable=True)
    risk_level = Column(String(16), nullable=True)
    parameters = Column(JSONB, nullable=True)
    output_summary = Column(Text, nullable=True)
    duration_ms = Column(Float, nullable=True)
    success = Column(String(8), nullable=True)  # "true" / "false"
    extra = Column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<AuditRecord {self.event_id} {self.event_type} {self.tool_name}>"


# ── DB persistence ────────────────────────────────────────

async def _persist_to_db(event: dict[str, Any]) -> None:
    """Try to persist an audit event to PostgreSQL. Silently no-op on failure."""
    try:
        from app.db import get_engine
        from sqlalchemy import insert

        engine = await get_engine()
        # Using raw insert to avoid session management complexity in background tasks
        async with engine.begin() as conn:
            await conn.execute(
                insert(AuditRecord).values(
                    event_id=event["event_id"],
                    event_type=event["event_type"],
                    agent=event.get("agent"),
                    tool_name=event.get("tool_name"),
                    risk_level=event.get("risk_level"),
                    parameters=event.get("parameters"),
                    output_summary=event.get("output_summary"),
                    duration_ms=event.get("duration_ms"),
                    success=event.get("success"),
                    extra=event.get("extra"),
                )
            )
        logger.debug("AUDIT DB | persisted event %s", event["event_id"])
    except Exception as exc:
        logger.debug("AUDIT DB | persistence skipped (DB unavailable): %s", exc)


# ── In-memory fallback for when DB is not available ───────

_in_memory_log: list[dict[str, Any]] = []


def log_event(
    *,
    event_type: str,
    agent: str | None = None,
    tool_name: str | None = None,
    risk_level: str | None = None,
    parameters: dict[str, Any] | None = None,
    output_summary: str | None = None,
    duration_ms: float | None = None,
    success: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record an audit event.  Persists to DB when available, falls back to in-memory.

    Returns the event dict.
    """
    event = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "agent": agent,
        "tool_name": tool_name,
        "risk_level": risk_level,
        "parameters": parameters,
        "output_summary": (output_summary[:500] if output_summary else None),
        "duration_ms": duration_ms,
        "success": "true" if success is True else ("false" if success is False else None),
        "extra": extra,
    }
    _in_memory_log.append(event)

    # Fire-and-forget DB persistence (don't block the agent loop)
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_persist_to_db(event))
    except RuntimeError:
        pass

    logger.info(
        "AUDIT | %s | tool=%s risk=%s success=%s duration=%.1fms",
        event_type,
        tool_name,
        risk_level,
        success,
        duration_ms or 0,
    )
    return event


def get_recent_events(limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent audit events from the in-memory log."""
    return _in_memory_log[-limit:]
