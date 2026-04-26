"""Tests for REST API routes."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "provider" in data
        assert "model" in data


class TestTaskCreation:
    def test_create_task_returns_201(self, client):
        resp = client.post("/api/v1/tasks", json={
            "task": "Fix the bug",
            "workspace_root": "/tmp/test",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "running"
        assert data["task_id"].startswith("task-")

    def test_create_task_empty_rejected(self, client):
        resp = client.post("/api/v1/tasks", json={"task": ""})
        assert resp.status_code == 422

    def test_create_task_with_options(self, client):
        resp = client.post("/api/v1/tasks", json={
            "task": "Add docstrings",
            "workspace_root": "/custom/path",
            "auto_approve_risk": "medium",
            "max_iterations": 10,
            "use_orchestrator": False,
        })
        assert resp.status_code == 201

    def test_create_task_without_workspace_uses_default(self, client):
        resp = client.post("/api/v1/tasks", json={"task": "Simple task"})
        assert resp.status_code == 201


class TestTaskStatus:
    def test_get_nonexistent_task(self, client):
        resp = client.get("/api/v1/tasks/nonexistent")
        assert resp.status_code == 404

    def test_get_task_after_creation(self, client):
        resp = client.post("/api/v1/tasks", json={"task": "Status check test"})
        task_id = resp.json()["task_id"]

        resp2 = client.get(f"/api/v1/tasks/{task_id}")
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["task_id"] == task_id
        assert data["status"] in ("running", "completed", "failed")

    def test_list_tasks(self, client):
        client.post("/api/v1/tasks", json={"task": "Task A"})
        client.post("/api/v1/tasks", json={"task": "Task B"})

        resp = client.get("/api/v1/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 2


class TestSSEStream:
    @pytest.mark.skip(reason="SSE streaming hangs with sync TestClient — tested manually or with async client")
    def test_stream_nonexistent_task(self, client):
        resp = client.get("/api/v1/tasks/nonexistent/stream")
        assert resp.status_code == 404

    @pytest.mark.skip(reason="SSE streaming hangs with sync TestClient — tested manually or with async client")
    def test_stream_headers_are_sse(self, client):
        resp = client.post("/api/v1/tasks", json={"task": "Stream test"})
        task_id = resp.json()["task_id"]
        resp2 = client.get(f"/api/v1/tasks/{task_id}/stream", follow_redirects=False)
        assert resp2.status_code in (200, 404)


class TestApproval:
    def test_approve_nonexistent_task(self, client):
        resp = client.post("/api/v1/tasks/nonexistent/approve", json={
            "approval_id": "apr-0001",
            "action": "approve",
        })
        assert resp.status_code == 404

    def test_approve_invalid_action(self, client):
        resp = client.post("/api/v1/tasks", json={"task": "Approval test"})
        task_id = resp.json()["task_id"]

        resp2 = client.post(f"/api/v1/tasks/{task_id}/approve", json={
            "approval_id": "apr-fake",
            "action": "invalid",
        })
        # Could be 400 (invalid action) or 404 (approval not found)
        assert resp2.status_code in (400, 404)


class TestTaskExecution:
    @pytest.mark.skip(reason="Background task blocks sync TestClient event loop — tested via integration")
    def test_full_task_lifecycle(self, client):
        """End-to-end: create task, check immediate status, then done."""
        resp = client.post("/api/v1/tasks", json={
            "task": "List files in the workspace",
            "use_orchestrator": True,
        })
        assert resp.status_code == 201
        task_id = resp.json()["task_id"]
        resp2 = client.get(f"/api/v1/tasks/{task_id}")
        assert resp2.status_code == 200
        assert resp2.json()["status"] in ("running", "completed", "failed")
