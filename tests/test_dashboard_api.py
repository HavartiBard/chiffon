"""Tests for the dashboard API layer and orchestrator proxy behavior."""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.dashboard import api as dashboard_api
from src.dashboard.api import session_store
from src.dashboard.main import app

ORCHESTRATOR_PLAN_ID = "plan-123"
ORCHESTRATOR_REQUEST_ID = "req-123"


@pytest.fixture
def test_client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_sessions() -> None:
    session_store.clear()
    yield
    session_store.clear()


@pytest.fixture
def orchestrator_stub(monkeypatch) -> Dict[str, Any]:
    plan_payload = {
        "plan_id": ORCHESTRATOR_PLAN_ID,
        "request_id": ORCHESTRATOR_REQUEST_ID,
        "human_readable_summary": "Deploy Kuma monitoring",
        "complexity_level": "simple",
        "status": "pending_approval",
        "estimated_duration_seconds": 120,
        "tasks": [
            {
                "order": 1,
                "name": "Check prerequisites",
                "work_type": "shell_script",
                "description": "Validate environment",
                "resource_requirements": {
                    "estimated_duration_seconds": 60,
                    "cpu_cores": 1,
                    "gpu_vram_mb": 0,
                },
            },
            {
                "order": 2,
                "name": "Deploy service",
                "work_type": "deploy_service",
                "description": "Create deployment",
                "resource_requirements": {
                    "estimated_duration_seconds": 60,
                    "cpu_cores": 1,
                    "gpu_vram_mb": 0,
                },
            },
        ],
    }

    state = {
        "approve_response": {
            "plan_id": ORCHESTRATOR_PLAN_ID,
            "status": "approved",
            "dispatch_started": True,
            "dispatch_result": {
                "dispatched_tasks": [{"task_id": "task-1"}, {"task_id": "task-2"}],
            },
        },
        "reject_response": {
            "plan_id": ORCHESTRATOR_PLAN_ID,
            "status": "rejected",
        },
        "cancel_calls": [],
    }

    async def fake_orchestrator_request(method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        if path.endswith("/request"):
            return {"request_id": ORCHESTRATOR_REQUEST_ID, "status": "parsing_complete"}
        if path == f"/api/v1/plan/{ORCHESTRATOR_REQUEST_ID}":
            return plan_payload
        if path == f"/api/v1/plan/{ORCHESTRATOR_PLAN_ID}/status":
            return {
                "plan_id": ORCHESTRATOR_PLAN_ID,
                "request_id": ORCHESTRATOR_REQUEST_ID,
                "status": "executing",
                "tasks": [
                    {"index": 0, "name": "Check prerequisites"},
                    {"index": 1, "name": "Deploy service"},
                ],
            }
        if path.endswith("/approve"):
            approved = kwargs.get("json", {}).get("approved", False)
            return state["approve_response"] if approved else state["reject_response"]
        if path.startswith("/api/v1/cancel/"):
            state["cancel_calls"].append(path.split("/")[-1])
            return {"status": "cancelled"}
        raise AssertionError(f"Unexpected orchestrator path: {path}")

    monkeypatch.setattr(
        dashboard_api, "_orchestrator_request", AsyncMock(side_effect=fake_orchestrator_request)
    )
    return {"plan_payload": plan_payload, "state": state}


def test_create_session_returns_session(test_client: TestClient) -> None:
    response = test_client.post("/api/dashboard/session", json={"user_id": "test-user"})

    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["user_id"] == "test-user"
    assert data["status"] == "idle"


def test_chat_returns_plan_and_messages(
    test_client: TestClient, orchestrator_stub: Dict[str, Any]
) -> None:
    session_response = test_client.post("/api/dashboard/session", json={"user_id": "deploy-user"})
    session_id = session_response.json()["session_id"]

    chat_response = test_client.post(
        "/api/dashboard/chat",
        json={"session_id": session_id, "message": "Deploy Kuma"},
    )

    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert payload["plan"]["plan_id"] == orchestrator_stub["plan_payload"]["plan_id"]
    assert len(payload["messages"]) == 2
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][1]["role"] == "assistant"


def test_approve_plan_triggers_dispatch(
    test_client: TestClient, orchestrator_stub: Dict[str, Any]
) -> None:
    session_response = test_client.post("/api/dashboard/session", json={"user_id": "approver"})
    session_id = session_response.json()["session_id"]

    test_client.post(
        "/api/dashboard/chat",
        json={"session_id": session_id, "message": "Deploy Kuma"},
    )

    approve_response = test_client.post(
        f"/api/dashboard/plan/{orchestrator_stub['plan_payload']['plan_id']}/approve",
        json={"session_id": session_id},
    )

    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"
    session = session_store.get_session(session_id)
    assert session.status == "executing"
    assert session.active_task_ids == ["task-1", "task-2"]


def test_reject_plan_resets_session(
    test_client: TestClient, orchestrator_stub: Dict[str, Any]
) -> None:
    session_response = test_client.post("/api/dashboard/session", json={"user_id": "rejector"})
    session_id = session_response.json()["session_id"]

    test_client.post(
        "/api/dashboard/chat",
        json={"session_id": session_id, "message": "Deploy Kuma"},
    )

    reject_response = test_client.post(
        f"/api/dashboard/plan/{orchestrator_stub['plan_payload']['plan_id']}/reject",
        json={"session_id": session_id},
    )

    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"
    session = session_store.get_session(session_id)
    assert session.status == "idle"
    assert any(
        msg.metadata.get("plan_id") == orchestrator_stub["plan_payload"]["plan_id"]
        for msg in session.messages
    )


def test_plan_status_returns_steps(
    test_client: TestClient, orchestrator_stub: Dict[str, Any]
) -> None:
    plan_id = orchestrator_stub["plan_payload"]["plan_id"]
    response = test_client.get(f"/api/dashboard/plan/{plan_id}/status")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "executing"
    assert len(data["steps"]) == 2


def test_abort_plan_cancels_tasks(
    test_client: TestClient, orchestrator_stub: Dict[str, Any]
) -> None:
    session_response = test_client.post("/api/dashboard/session", json={"user_id": "aborter"})
    session_id = session_response.json()["session_id"]

    session = session_store.get_session(session_id)
    session.current_plan_id = ORCHESTRATOR_PLAN_ID
    session.active_task_ids = ["task-1"]

    response = test_client.post(
        f"/api/dashboard/plan/{ORCHESTRATOR_PLAN_ID}/abort",
        json={"session_id": session_id},
    )

    assert response.status_code == 200
    assert response.json()["cancelled"] == 1
    assert orchestrator_stub["state"]["cancel_calls"] == ["task-1"]
