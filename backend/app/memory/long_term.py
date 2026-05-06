"""Long-term memory — ChromaDB vector store for persistent knowledge.

Three collections:
  1. fix_patterns      — successful bug fixes and their patterns
  2. project_conventions — coding style, architecture patterns, naming rules
  3. user_preferences  — explicit user feedback and preferences

Memories are stored as text chunks with metadata and retrieved via
semantic similarity search when starting new tasks.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings

logger = logging.getLogger("codesentry.memory.long_term")

# ── Data models ────────────────────────────────────────────


@dataclass
class MemoryEntry:
    """A single long-term memory entry."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    collection: str = "fix_patterns"  # fix_patterns | project_conventions | user_preferences
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── ChromaDB client (lazy singleton) ───────────────────────

_client: Any = None


def _get_chroma_client():
    """Return a persistent ChromaDB client, creating it on first call."""
    global _client
    if _client is None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        settings = get_settings()
        try:
            # Try connecting to the ChromaDB server
            _client = chromadb.HttpClient(
                host=settings.chroma_host,
                port=settings.chroma_port,
            )
            logger.info("ChromaDB connected at %s:%d", settings.chroma_host, settings.chroma_port)
        except Exception:
            # Fallback to in-memory / persistent local
            import os
            persist_dir = os.path.join(os.path.dirname(__file__), "..", "..", "chroma_data")
            os.makedirs(persist_dir, exist_ok=True)
            _client = chromadb.PersistentClient(
                path=persist_dir,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            logger.info("ChromaDB using persistent local storage at %s", persist_dir)
    return _client


def _get_embedding_fn():
    """Return an embedding function. Uses sentence-transformers as default.

    This is a LOCAL embedding model — no API key required.
    """
    try:
        from chromadb.utils import embedding_functions
        return embedding_functions.DefaultEmbeddingFunction()
    except Exception:
        # Ultra-minimal fallback: random embeddings (for tests only)
        logger.warning("DefaultEmbeddingFunction unavailable, using fallback")
        return None


# Collection names
COLLECTIONS = {
    "fix_patterns": "Successful bug fixes, patches, and their resolution patterns",
    "project_conventions": "Project-specific coding conventions, architecture, naming rules",
    "user_preferences": "User feedback, preferences, and explicit instructions",
}


def _get_or_create_collection(name: str):
    """Get or create a named ChromaDB collection."""
    client = _get_chroma_client()
    ef = _get_embedding_fn()

    try:
        return client.get_collection(name=name, embedding_function=ef)
    except Exception:
        logger.info("Creating new ChromaDB collection: %s", name)
        return client.create_collection(
            name=name,
            embedding_function=ef,
            metadata={"description": COLLECTIONS.get(name, "")},
        )


# ── Public API ─────────────────────────────────────────────


async def store_memory(
    content: str,
    collection: str = "fix_patterns",
    metadata: dict[str, Any] | None = None,
) -> str:
    """Store a memory entry in the specified collection.

    Args:
        content: The text content to store.
        collection: One of 'fix_patterns', 'project_conventions', 'user_preferences'.
        metadata: Optional dict with keys like task_type, files, language, etc.

    Returns:
        The memory entry ID.
    """
    if collection not in COLLECTIONS:
        raise ValueError(f"Unknown collection '{collection}'. Choose from: {list(COLLECTIONS)}")

    entry = MemoryEntry(
        collection=collection,
        content=content,
        metadata=metadata or {},
    )

    try:
        col = _get_or_create_collection(collection)
        col.add(
            ids=[entry.id],
            documents=[content],
            metadatas=[{
                **(metadata or {}),
                "timestamp": entry.timestamp,
                "collection": collection,
            }],
        )
        logger.info(
            "MEMORY STORE | collection=%s id=%s content_len=%d",
            collection, entry.id, len(content),
        )
        return entry.id
    except Exception as exc:
        logger.error("Failed to store memory: %s", exc)
        # Store in memory as fallback
        _fallback_memory.append(entry)
        return entry.id


async def search_memories(
    query: str,
    collection: str = "fix_patterns",
    n_results: int = 5,
) -> list[dict[str, Any]]:
    """Search for relevant memories using semantic similarity.

    Args:
        query: The search query text.
        collection: Which collection to search.
        n_results: Max number of results to return.

    Returns:
        List of dicts with keys: id, content, metadata, distance.
    """
    if collection not in COLLECTIONS:
        raise ValueError(f"Unknown collection '{collection}'.")

    # Search fallback memory too
    fallback_results = _search_fallback(query, collection, n_results)

    try:
        col = _get_or_create_collection(collection)
        if col.count() == 0:
            return fallback_results

        results = col.query(query_texts=[query], n_results=n_results)
        entries = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, mem_id in enumerate(ids):
            entries.append({
                "id": mem_id,
                "content": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) else {},
                "distance": distances[i] if i < len(distances) else None,
            })

        logger.info(
            "MEMORY SEARCH | collection=%s query='%s...' results=%d",
            collection, query[:60], len(entries),
        )
        return entries + fallback_results

    except Exception as exc:
        logger.warning("ChromaDB search failed, using fallback: %s", exc)
        return fallback_results


async def extract_and_store_insights(
    task: str,
    final_summary: str,
    files_involved: list[str] | None = None,
) -> list[str]:
    """After a task completes, extract key insights and store them.

    Called by the Orchestrator after phase 4 (Done).

    Returns list of stored memory IDs.
    """
    ids: list[str] = []

    # Store as a fix pattern
    task_lower = task.lower()
    if any(kw in task_lower for kw in ("fix", "bug", "error", "issue", "broken")):
        meta = {"task_type": "bug_fix", "source": "auto_extracted"}
        if files_involved:
            meta["files"] = ",".join(files_involved)
        ids.append(await store_memory(
            content=f"Task: {task}\n\nResolution:\n{final_summary[:2000]}",
            collection="fix_patterns",
            metadata=meta,
        ))

    # Store project conventions (if any files were involved)
    if files_involved:
        ids.append(await store_memory(
            content=f"Files modified: {', '.join(files_involved)}\nTask: {task}\nSummary: {final_summary[:1000]}",
            collection="project_conventions",
            metadata={
                "task_type": "code_change",
                "files": ",".join(files_involved),
                "source": "auto_extracted",
            },
        ))
    else:
        # Store even without specific files — general task experience
        ids.append(await store_memory(
            content=f"Task: {task}\nSummary: {final_summary[:1000]}",
            collection="project_conventions",
            metadata={
                "task_type": "general",
                "source": "auto_extracted",
            },
        ))

    logger.info("MEMORY EXTRACT | stored %d insights for task", len(ids))
    return ids


async def get_collection_stats() -> dict[str, int]:
    """Return the count of entries in each collection."""
    stats = {}
    for name in COLLECTIONS:
        try:
            col = _get_or_create_collection(name)
            stats[name] = col.count()
        except Exception:
            stats[name] = len([m for m in _fallback_memory if m.collection == name])
    return stats


async def clear_collection(collection: str, clear_fallback: bool = False) -> int:
    """Delete all entries in a collection. Returns count deleted.

    Args:
        collection: Which collection to clear.
        clear_fallback: If True, also clear the in-memory fallback store.
    """
    count = 0
    try:
        col = _get_or_create_collection(collection)
        count = col.count()
        if count > 0:
            all_ids = col.get()["ids"]
            if all_ids:
                col.delete(ids=all_ids)
    except Exception:
        pass

    # Only clear fallback when explicitly requested (avoids cross-test contamination)
    if clear_fallback:
        global _fallback_memory
        before = len(_fallback_memory)
        _fallback_memory = [m for m in _fallback_memory if m.collection != collection]
        count += before - len(_fallback_memory)
    return count


# ── In-memory fallback ─────────────────────────────────────

_fallback_memory: list[MemoryEntry] = []


def _search_fallback(query: str, collection: str, n_results: int) -> list[dict[str, Any]]:
    """Simple keyword-based fallback search."""
    query_lower = query.lower()
    keywords = set(query_lower.split())
    scored = []

    for entry in _fallback_memory:
        if entry.collection != collection:
            continue
        content_lower = entry.content.lower()
        score = sum(1 for kw in keywords if kw in content_lower)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "id": e.id,
            "content": e.content[:500],
            "metadata": e.metadata,
            "distance": 1.0 / (score + 1),
        }
        for score, e in scored[:n_results]
    ]
