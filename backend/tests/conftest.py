"""Shared test fixtures for CodeSentry."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def temp_workspace() -> Path:
    """Create a temporary workspace directory for isolated testing."""
    with tempfile.TemporaryDirectory(prefix="codesentry_test_") as tmp:
        yield Path(tmp)


@pytest.fixture
def test_settings(temp_workspace: Path) -> Settings:
    """Return settings overridden for testing."""
    return Settings(
        model_provider="openai",
        model_name="gpt-4o",
        model_base_url="https://api.openai.com/v1",
        model_api_key="sk-test",
        max_iterations=5,
        workspace_root=temp_workspace,
        postgres_host="localhost",
        postgres_port=5432,
        postgres_user="test",
        postgres_password="test",
        postgres_db="test",
        chroma_host="localhost",
        chroma_port=8000,
        redis_host="localhost",
        redis_port=6379,
        prompt_cache_enabled=False,
        auto_approve_risk_level="low",
    )


@pytest.fixture
def client() -> TestClient:
    """Return a FastAPI TestClient for the app."""
    app = create_app()
    return TestClient(app)
