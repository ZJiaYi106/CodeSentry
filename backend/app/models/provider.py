"""Model provider factory — unified interface over OpenAI, Anthropic, and Hermes.

No provider is hardcoded into business logic.  Switch via MODEL_PROVIDER env var.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.config import ModelProvider, get_settings

logger = logging.getLogger(__name__)

# Cache the model instance so we don't re-create on every call
_model: BaseChatModel | None = None
_model_provider: ModelProvider | None = None
_model_name: str | None = None


def _create_openai_model() -> BaseChatModel:
    """Create a ChatOpenAI instance."""
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    return ChatOpenAI(
        model=settings.model_name,
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        temperature=settings.agent_temperature,
        max_tokens=4096,
        request_timeout=120,
        max_retries=2,
    )


def _create_anthropic_model() -> BaseChatModel:
    """Create a ChatAnthropic instance."""
    from langchain_anthropic import ChatAnthropic

    settings = get_settings()
    return ChatAnthropic(
        model=settings.model_name,
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        temperature=settings.agent_temperature,
        max_tokens=4096,
        request_timeout=120,
        max_retries=2,
    )


def _create_hermes_model() -> BaseChatModel:
    """Create a ChatOpenAI instance pointing at a Hermes-compatible endpoint."""
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    return ChatOpenAI(
        model=settings.model_name,
        base_url=settings.model_base_url,
        api_key=settings.model_api_key or "not-needed",
        temperature=settings.agent_temperature,
        max_tokens=4096,
        request_timeout=120,
        max_retries=2,
    )


_FACTORIES = {
    ModelProvider.OPENAI: _create_openai_model,
    ModelProvider.ANTHROPIC: _create_anthropic_model,
    ModelProvider.HERMES: _create_hermes_model,
}


def get_model() -> BaseChatModel:
    """Return the configured chat model, creating it on first call.

    Re-creates the instance if MODEL_PROVIDER or MODEL_NAME has changed.
    """
    global _model, _model_provider, _model_name

    settings = get_settings()
    if (
        _model is None
        or _model_provider != settings.model_provider
        or _model_name != settings.model_name
    ):
        factory = _FACTORIES.get(settings.model_provider)
        if factory is None:
            raise ValueError(
                f"Unknown MODEL_PROVIDER '{settings.model_provider.value}'. "
                f"Choose from: {[p.value for p in ModelProvider]}"
            )
        logger.info(
            "Creating model: provider=%s model=%s",
            settings.model_provider.value,
            settings.model_name,
        )
        _model = factory()
        _model_provider = settings.model_provider
        _model_name = settings.model_name

    return _model


def reset_model_cache() -> None:
    """Clear the cached model instance (useful for testing)."""
    global _model, _model_provider, _model_name
    _model = None
    _model_provider = None
    _model_name = None


# ── Message helpers ────────────────────────────────────────

def msg_system(content: str) -> SystemMessage:
    return SystemMessage(content=content)


def msg_human(content: str) -> HumanMessage:
    return HumanMessage(content=content)


def msg_ai(content: str) -> AIMessage:
    return AIMessage(content=content)
