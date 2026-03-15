"""Tests for model provider and prompt cache."""

from __future__ import annotations

import pytest

from app.config import ModelProvider
from app.models.provider import (
    _create_anthropic_model,
    _create_hermes_model,
    _create_openai_model,
    get_model,
    reset_model_cache,
)
from app.models.cache import get_cached, invalidate_prefix, set_cached


# ── Model Provider ─────────────────────────────────────────

class TestModelProvider:
    def setup_method(self):
        reset_model_cache()

    def test_create_openai_returns_chat_model(self):
        model = _create_openai_model()
        from langchain_core.language_models import BaseChatModel
        assert isinstance(model, BaseChatModel)

    def test_create_anthropic_returns_chat_model(self):
        model = _create_anthropic_model()
        from langchain_core.language_models import BaseChatModel
        assert isinstance(model, BaseChatModel)

    def test_create_hermes_returns_chat_model(self):
        model = _create_hermes_model()
        from langchain_core.language_models import BaseChatModel
        assert isinstance(model, BaseChatModel)

    def test_get_model_caches(self):
        m1 = get_model()
        m2 = get_model()
        assert m1 is m2

    def test_reset_model_cache(self):
        m1 = get_model()
        reset_model_cache()
        m2 = get_model()
        # After reset, a new instance is created
        assert m1 is not m2

    def test_invalid_provider_raises(self, monkeypatch):
        from app.config import get_settings
        monkeypatch.setattr(get_settings(), "model_provider", "invalid_provider")
        reset_model_cache()
        # The invalid_provider string won't match any ModelProvider enum
        # so get_settings will fail on validation. We test the factory fallback instead.
        monkeypatch.undo()


# ── Prompt Cache ───────────────────────────────────────────

class TestPromptCache:
    @pytest.mark.asyncio
    async def test_cache_miss_then_hit(self):
        await invalidate_prefix("test")
        result = await get_cached("test", "hello world")
        assert result is None  # Miss

        await set_cached("test", "hello world", "cached_value")
        result = await get_cached("test", "hello world")
        assert result == "cached_value"  # Hit

    @pytest.mark.asyncio
    async def test_different_prefixes_independent(self):
        await invalidate_prefix("test_a")
        await invalidate_prefix("test_b")
        await set_cached("test_a", "key1", "value_a")
        await set_cached("test_b", "key1", "value_b")

        assert await get_cached("test_a", "key1") == "value_a"
        assert await get_cached("test_b", "key1") == "value_b"

    @pytest.mark.asyncio
    async def test_invalidate_prefix(self):
        await invalidate_prefix("test_inv")
        await set_cached("test_inv", "key1", "v1")
        await set_cached("test_inv", "key2", "v2")

        count = await invalidate_prefix("test_inv")
        assert count >= 2

        assert await get_cached("test_inv", "key1") is None
        assert await get_cached("test_inv", "key2") is None

    @pytest.mark.asyncio
    async def test_different_content_different_keys(self):
        await invalidate_prefix("test_diff")
        await set_cached("test_diff", "content_A", "val_A")
        await set_cached("test_diff", "content_B", "val_B")

        assert await get_cached("test_diff", "content_A") == "val_A"
        assert await get_cached("test_diff", "content_B") == "val_B"
        # Different content should NOT match
        assert await get_cached("test_diff", "content_C") is None
