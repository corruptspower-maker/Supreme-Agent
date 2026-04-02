"""Tests for the FastAPI web UI."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestWebUI:
    @pytest.fixture
    def app(self):
        from src.interface.web import create_app

        return create_app(agent=None)

    @pytest.fixture
    def app_with_agent(self):
        from src.core.models import SafetyMode
        from src.interface.web import create_app

        mock_agent = MagicMock()
        mock_agent.get_status.return_value = {
            "running": True,
            "paused": False,
            "safety_mode": SafetyMode.FULL.value,
            "active_tasks": 0,
            "queued_tasks": 0,
            "reasoning_buffer": ["Planning: test task"],
            "circuit_breaker_states": {"tier1": False, "tier2": False, "tier3": False},
        }
        mock_task = MagicMock()
        mock_task.id = "test-task-id"
        mock_task.status = MagicMock()
        mock_task.status.value = "pending"
        mock_agent.submit_request = AsyncMock(return_value=mock_task)
        mock_agent._reasoning_buffer = ["Planning: test task"]

        return create_app(agent=mock_agent)

    def test_dashboard_returns_html(self, app):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Supreme Agent" in resp.text
        assert "<!DOCTYPE html>" in resp.text

    def test_status_no_agent(self, app):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False

    def test_status_with_agent(self, app_with_agent):
        from fastapi.testclient import TestClient

        client = TestClient(app_with_agent)
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert data["safety_mode"] == "full"

    def test_submit_task_no_agent_returns_503(self, app):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post("/tasks", json={"text": "do something"})
        assert resp.status_code == 503

    def test_submit_task_with_agent(self, app_with_agent):
        from fastapi.testclient import TestClient

        client = TestClient(app_with_agent)
        resp = client.post("/tasks", json={"text": "find a file", "source": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "test-task-id"
        assert data["status"] == "pending"

    def test_submit_task_empty_text(self, app_with_agent):
        """Empty task text should still be submitted (validation is agent-side)."""
        from fastapi.testclient import TestClient

        client = TestClient(app_with_agent)
        resp = client.post("/tasks", json={"text": ""})
        # FastAPI will accept it; agent validates content
        assert resp.status_code == 200
