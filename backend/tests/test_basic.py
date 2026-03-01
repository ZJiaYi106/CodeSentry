"""Basic sanity tests for the Phase 1 skeleton."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint():
    """Verify /health returns ok."""
    app = create_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"


def test_status_endpoint():
    """Verify /api/v1/status returns provider info."""
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/v1/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "provider" in data
    assert "model" in data
    assert "workspace" in data


def test_config_singleton():
    """Verify settings are cached as singleton."""
    from app.config import get_settings

    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_workspace_root_is_path():
    """Verify workspace_root is a Path object."""
    from pathlib import Path

    from app.config import get_settings

    s = get_settings()
    assert isinstance(s.workspace_root, Path)
