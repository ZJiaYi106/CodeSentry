"""Context compression — summarizes conversation history when it exceeds the token threshold."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.config import get_settings

logger = logging.getLogger("codesentry.compressor")

# Approximate token count: ~4 chars per token for English text
_CHARS_PER_TOKEN = 4


def estimate_tokens(messages: list[BaseMessage]) -> int:
    """Rough token estimate across all messages."""
    total = 0
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        total += len(content) // _CHARS_PER_TOKEN
    return total


def _build_truncation_header(original_count: int, kept_count: int, summary: str) -> str:
    return (
        f"[CONTEXT COMPRESSED: {original_count} messages → {kept_count} + summary. "
        f"Summary of removed messages:\n{summary}\n"
        f"--- END OF COMPRESSION HEADER ---]"
    )


async def compress_if_needed(
    messages: list[BaseMessage],
    model: Any,
    threshold_tokens: int | None = None,
) -> list[BaseMessage]:
    """If total estimated tokens exceed the threshold, compress older messages.

    Keeps:
      - System messages (always preserved at the top)
      - Last 6 messages (most recent context)
      - A compressed summary of everything in between

    Returns a new list (does not mutate the input).
    """
    if threshold_tokens is None:
        threshold_tokens = get_settings().context_compression_threshold_tokens

    current_tokens = estimate_tokens(messages)
    if current_tokens <= threshold_tokens:
        logger.debug(
            "Compression not needed: %d tokens ≤ %d threshold",
            current_tokens,
            threshold_tokens,
        )
        return messages

    logger.info(
        "Compressing context: %d tokens > %d threshold — %d messages",
        current_tokens,
        threshold_tokens,
        len(messages),
    )

    # Separate system messages
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    non_system = [m for m in messages if not isinstance(m, SystemMessage)]

    if len(non_system) <= 6:
        return messages  # Nothing to compress

    # Keep last 6, summarize the rest
    to_summarize = non_system[:-6]
    recent = non_system[-6:]

    # Build a summary of older messages
    summary_text = ""
    for msg in to_summarize:
        role = "Human" if isinstance(msg, HumanMessage) else "AI" if isinstance(msg, AIMessage) else "System"
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        summary_text += f"[{role}]: {content[:200]}\n"

    # Use the model to compress if available, otherwise use truncation
    compressed_summary = summary_text
    try:
        if model is not None and hasattr(model, "invoke"):
            compress_prompt = (
                "Summarize the following conversation history into a dense paragraph. "
                "Keep all key facts, decisions, file paths, code snippets, and error messages:\n\n"
                + summary_text
            )
            result = await model.ainvoke([HumanMessage(content=compress_prompt)])
            compressed_summary = result.content if hasattr(result, "content") else str(result)
    except Exception as exc:
        logger.warning("Model-based compression failed, using truncation: %s", exc)

    # Reconstruct
    header = _build_truncation_header(len(non_system), len(recent), compressed_summary)
    compressed = system_msgs + [HumanMessage(content=header)] + recent

    new_tokens = estimate_tokens(compressed)
    logger.info(
        "Compression complete: %d → %d tokens (%d messages → %d)",
        current_tokens,
        new_tokens,
        len(messages),
        len(compressed),
    )
    return compressed
