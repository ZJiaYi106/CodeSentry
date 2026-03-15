"""Prompt cache — caches stable prompt prefixes in Redis.

Cached blocks:
  - System prompt (agent role definition, rules)
  - Repo summary (static until files change)
  - Tool definitions (static until tools change)

Cache hit/miss is logged for observability.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger("codesentry.cache")

# In-memory fallback when Redis is unavailable
_memory_cache: dict[str, tuple[str, float]] = {}


def _cache_key(prefix: str, content: str) -> str:
    """Generate a deterministic cache key."""
    h = hashlib.sha256(f"{prefix}:{content}".encode()).hexdigest()[:32]
    return f"codesentry:prompt:{prefix}:{h}"


async def _get_redis():
    """Return a Redis connection, or None if unavailable."""
    try:
        import redis.asyncio as aioredis

        settings = get_settings()
        return aioredis.from_url(settings.redis_dsn, decode_responses=True)
    except Exception:
        return None


async def get_cached(prefix: str, content: str) -> str | None:
    """Check if `content` is cached under `prefix`.

    Returns the cached value on hit, None on miss.
    """
    if not get_settings().prompt_cache_enabled:
        logger.debug("Prompt cache disabled — skipping lookup for %s", prefix)
        return None

    key = _cache_key(prefix, content)

    # Try Redis first
    redis = await _get_redis()
    if redis is not None:
        try:
            cached = await redis.get(key)
            if cached:
                logger.info("CACHE HIT  | prefix=%s key=%s", prefix, key)
                return cached
            else:
                logger.info("CACHE MISS | prefix=%s key=%s", prefix, key)
                return None
        except Exception as exc:
            logger.warning("Redis error during cache lookup: %s", exc)

    # Fallback to in-memory
    import time
    now = time.time()
    if key in _memory_cache:
        value, _ = _memory_cache[key]
        logger.info("CACHE HIT  | prefix=%s key=%s (memory)", prefix, key)
        return value

    logger.info("CACHE MISS | prefix=%s key=%s (memory)", prefix, key)
    return None


async def set_cached(prefix: str, content: str, value: str) -> None:
    """Store `value` under `prefix` keyed by `content`."""
    if not get_settings().prompt_cache_enabled:
        return

    key = _cache_key(prefix, content)
    settings = get_settings()

    # Try Redis
    redis = await _get_redis()
    if redis is not None:
        try:
            await redis.set(key, value, ex=settings.prompt_cache_ttl_seconds)
            logger.info("CACHE SET  | prefix=%s key=%s ttl=%ds", prefix, key, settings.prompt_cache_ttl_seconds)
            return
        except Exception as exc:
            logger.warning("Redis error during cache set: %s", exc)

    # Fallback to in-memory
    import time
    _memory_cache[key] = (value, time.time() + settings.prompt_cache_ttl_seconds)
    logger.info("CACHE SET  | prefix=%s key=%s (memory)", prefix, key)


async def invalidate_prefix(prefix: str) -> int:
    """Remove all cache entries under `prefix`. Returns count removed."""
    count = 0
    pattern = f"codesentry:prompt:{prefix}:*"

    # Memory cache
    import time
    now = time.time()
    expired = [k for k, (_, exp) in _memory_cache.items() if exp < now]
    for k in expired:
        del _memory_cache[k]

    to_remove = [k for k in _memory_cache if k.startswith(f"codesentry:prompt:{prefix}:")]
    for k in to_remove:
        del _memory_cache[k]
    count += len(to_remove)

    # Redis
    redis = await _get_redis()
    if redis is not None:
        try:
            keys = []
            async for k in redis.scan_iter(match=pattern):
                keys.append(k)
            if keys:
                await redis.delete(*keys)
                count += len(keys)
        except Exception as exc:
            logger.warning("Redis error during cache invalidation: %s", exc)

    logger.info("CACHE INVALIDATE | prefix=%s removed=%d", prefix, count)
    return count
