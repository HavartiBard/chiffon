"""Integration tests covering Dashboard ↔ Orchestrator interaction."""

from __future__ import annotations

import asyncio

import pytest
import socketio
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.dashboard.api import _format_plan_for_dashboard, session_store
from src.dashboard.main import app


@pytest.fixture(autouse=True)
def clear_sessions() -> None:
    session_store.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def orchestrator_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, str, dict | None, dict | None]]:
    calls: list[tuple[str, str, dict | None, dict | None]] = []

    async def fake_request(
        method: str, path: str, json: dict | None = None, params: dict | None = None
    ) -> dict:
        calls.append((method, path, json, params))
        if path == "/api/v1/request":
            return {"request_id": "req-321", "status": "parsing_complete"}
        if path.startswith("/api/v1/plan/") and path.endswith("/status"):
            return {
                "plan_id": "plan-321",
                "status": "executing",
                "tasks": [
                    {"index": 0, "name": "Step 1", "status": "completed", "output": "ok"},
                    {"index": 1, "name": "Step 2", "status": "running"},
                ],
            }
        if path.startswith("/api/v1/plan/") and path.endswith("/approve"):
            return {"status": "approved", "dispatch_started": True}
        if path.startswith("/api/v1/plan/") and not path.endswith("/status"):
            return {
                "plan_id": "plan-321",
                "request_id": "req-321",
                "human_readable_summary": "Deploy Kuma",
                "tasks": [{"name": "Check prerequisites", "work_type": "shell_script"}],
                "complexity_level": "simple",
                "status": "pending_approval",
            }
        return {}

    monkeypatch.setattr("src.dashboard.api._orchestrator_request", fake_request)
    return calls


class TestDashboardOrchestratorProxy:
    def test_chat_proxies_request(self, client: TestClient, orchestrator_calls: list) -> None:
        session_id = client.post("/api/dashboard/session", json={"user_id": "test"}).json()[
            "session_id"
        ]
        client.post(
            "/api/dashboard/chat", json={"session_id": session_id, "message": "Deploy Kuma"}
        )
        paths = [call[1] for call in orchestrator_calls]
        assert "/api/v1/request" in paths
        assert any(path.startswith("/api/v1/plan/req-321") for path in paths)

    def test_plan_approval_proxies(self, client: TestClient, orchestrator_calls: list) -> None:
        session_id = client.post("/api/dashboard/session", json={"user_id": "test"}).json()[
            "session_id"
        ]
        client.post("/api/dashboard/plan/plan-321/approve", json={"session_id": session_id})
        assert any("/api/v1/plan/plan-321/approve" in call[1] for call in orchestrator_calls)

    def test_plan_rejection_proxies(self, client: TestClient, orchestrator_calls: list) -> None:
        session_id = client.post("/api/dashboard/session", json={"user_id": "test"}).json()[
            "session_id"
        ]
        client.post("/api/dashboard/plan/plan-321/reject", json={"session_id": session_id})
        assert any("/api/v1/plan/plan-321/approve" in call[1] for call in orchestrator_calls)


class TestPlanFormatting:
    def test_risk_level_from_complexity(self) -> None:
        plan = {
            "plan_id": "p1",
            "request_id": "req-1",
            "complexity_level": "simple",
            "tasks": [],
            "human_readable_summary": "Test",
        }
        formatted = _format_plan_for_dashboard(plan)
        assert formatted.risk_level == "low"
        plan["complexity_level"] = "medium"
        formatted = _format_plan_for_dashboard(plan)
        assert formatted.risk_level == "medium"
        plan["complexity_level"] = "complex"
        formatted = _format_plan_for_dashboard(plan)
        assert formatted.risk_level == "high"

    def test_duration_estimate_created(self) -> None:
        plan = {
            "plan_id": "p1",
            "request_id": "req-1",
            "complexity_level": "simple",
            "tasks": [
                {"resource_requirements": {"estimated_duration_seconds": 60}},
                {"resource_requirements": {"estimated_duration_seconds": 120}},
            ],
            "human_readable_summary": "Test",
        }
        formatted = _format_plan_for_dashboard(plan)
        assert "~" in formatted.estimated_duration

    def test_steps_converted_to_checklist(self) -> None:
        plan = {
            "plan_id": "p1",
            "request_id": "req-1",
            "complexity_level": "simple",
            "tasks": [
                {"order": 1, "name": "Step 1", "work_type": "shell"},
                {"order": 2, "name": "Step 2", "work_type": "docker"},
            ],
            "human_readable_summary": "Test",
        }
        formatted = _format_plan_for_dashboard(plan)
        assert len(formatted.steps) == 2


class TestErrorHandling:
    def test_orchestrator_timeout(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def failing_request(*args, **kwargs):
            raise asyncio.TimeoutError()

        monkeypatch.setattr("src.dashboard.api._orchestrator_request", failing_request)
        session_id = client.post("/api/dashboard/session", json={"user_id": "test"}).json()[
            "session_id"
        ]
        response = client.post(
            "/api/dashboard/chat", json={"session_id": session_id, "message": "Deploy"}
        )
        assert response.status_code == 502

    def test_orchestrator_error_response(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def error_request(*args, **kwargs):
            raise HTTPException(status_code=404, detail="Plan missing")

        monkeypatch.setattr("src.dashboard.api._orchestrator_request", error_request)
        response = client.get("/api/dashboard/plan/missing")
        assert response.status_code == 404


class TestWebSocketIntegration:
    @pytest.mark.asyncio
    async def test_websocket_ping(self) -> None:
        pytest.skip("WebSocket testing requires live server; TestClient cannot serve WebSocket")

    @pytest.mark.asyncio
    async def test_websocket_subscribe_unsubscribe(self) -> None:
        pytest.skip("WebSocket testing requires live server; TestClient cannot serve WebSocket")
