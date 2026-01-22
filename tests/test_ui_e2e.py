"""End-to-end UI workflow tests for Phase 7."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.dashboard.api import session_store
from src.dashboard.main import app


class OrchestratorStub:
    def __init__(self) -> None:
        self.request_counter = 0
        self.plan_payloads: dict[str, dict] = {}
        self.plan_statuses: dict[str, dict] = {}
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []

    def register_plan(self, request_id: str, payload: dict) -> None:
        self.plan_payloads[request_id] = payload
        plan_id = payload.get("plan_id")
        if plan_id:
            self.plan_statuses[plan_id] = {
                "plan_id": plan_id,
                "status": payload.get("status", "pending_approval"),
                "tasks": payload.get("tasks", []),
            }

    async def __call__(
        self, method: str, path: str, json: dict | None = None, params: dict | None = None
    ) -> dict:
        self.calls.append((method, path, json, params))
        if path == "/api/v1/request":
            self.request_counter += 1
            request_id = f"req-{123 + self.request_counter - 1}"
            return {"request_id": request_id, "status": "parsing_complete"}

        if path.endswith("/status"):
            plan_id = path.split("/api/v1/plan/")[1].split("/")[0]
            return self.plan_statuses.get(
                plan_id,
                {
                    "plan_id": "plan-123",
                    "status": "executing",
                    "tasks": [
                        {"index": 0, "name": "Step 1", "status": "running"},
                    ],
                },
            )

        if path.endswith("/approve"):
            if json and not json.get("approved", True):
                return {"status": "rejected"}
            return {
                "status": "approved",
                "dispatch_started": True,
                "dispatch_result": {"dispatched_tasks": [{"task_id": "task-1"}]},
            }

        if path.startswith("/api/v1/cancel/"):
            return {"status": "cancelled"}

        if path.endswith("/modify"):
            return {
                "new_plan": {
                    "plan_id": "plan-124",
                    "request_id": "req-124",
                    "human_readable_summary": "Deploy Kuma to staging",
                    "tasks": [
                        {"name": "Step 1", "work_type": "deploy_service"},
                    ],
                    "complexity_level": "medium",
                    "status": "pending_approval",
                }
            }

        rest = path.split("/api/v1/plan/")[1]
        if rest in self.plan_payloads:
            return self.plan_payloads[rest]

        return {}


@pytest.fixture(autouse=True)
def clear_sessions() -> None:
    session_store.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def orchestrator_stub(monkeypatch: pytest.MonkeyPatch) -> OrchestratorStub:
    stub = OrchestratorStub()
    stub.register_plan(
        "req-123",
        {
            "plan_id": "plan-123",
            "request_id": "req-123",
            "human_readable_summary": "Deploy Kuma to homelab",
            "tasks": [
                {"name": "Check prerequisites", "work_type": "shell_script", "status": "pending"},
                {"name": "Deploy Kuma", "work_type": "deploy_service", "status": "pending"},
            ],
            "complexity_level": "simple",
            "status": "pending_approval",
        },
    )
    monkeypatch.setattr("src.dashboard.api._orchestrator_request", stub)
    return stub


class TestChatWorkflow:
    def test_create_session(self, client: TestClient) -> None:
        response = client.post("/api/dashboard/session", json={"user_id": "test-user"})
        assert response.status_code == 200
        payload = response.json()
        assert "session_id" in payload
        assert payload["status"] == "idle"

    def test_send_deployment_request(
        self, client: TestClient, orchestrator_stub: OrchestratorStub
    ) -> None:
        session_id = client.post("/api/dashboard/session", json={"user_id": "test-user"}).json()[
            "session_id"
        ]
        response = client.post(
            "/api/dashboard/chat",
            json={"session_id": session_id, "message": "Deploy Kuma to homelab"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) >= 2
        assert data["plan"]["plan_id"] == "plan-123"

    def test_chat_handles_modification_request(
        self, client: TestClient, orchestrator_stub: OrchestratorStub
    ) -> None:
        session_id = client.post("/api/dashboard/session", json={"user_id": "test-user"}).json()[
            "session_id"
        ]
        orchestrator_stub.register_plan(
            "req-124",
            {
                "plan_id": "plan-124",
                "request_id": "req-124",
                "human_readable_summary": "Modified plan",
                "tasks": [{"name": "New step", "work_type": "shell_script"}],
                "complexity_level": "medium",
                "status": "pending_approval",
            },
        )

        client.post(
            "/api/dashboard/chat", json={"session_id": session_id, "message": "Deploy Kuma"}
        )
        response = client.post(
            "/api/dashboard/chat",
            json={"session_id": session_id, "message": "Use staging environment"},
        )
        assert response.status_code == 200
        assert "plan" in response.json()


class TestPlanReviewWorkflow:
    def test_get_plan_formatted_for_ui(
        self, client: TestClient, orchestrator_stub: OrchestratorStub
    ) -> None:
        session_id = client.post("/api/dashboard/session", json={"user_id": "test-user"}).json()[
            "session_id"
        ]
        chat_response = client.post(
            "/api/dashboard/chat",
            json={"session_id": session_id, "message": "Deploy Kuma"},
        )
        plan_id = chat_response.json()["plan"]["plan_id"]
        response = client.get(f"/api/dashboard/plan/{plan_id}")
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "steps" in data
        assert "estimated_duration" in data
        assert "risk_level" in data

    def test_approve_plan_triggers_execution(
        self, client: TestClient, orchestrator_stub: OrchestratorStub
    ) -> None:
        session_id = client.post("/api/dashboard/session", json={"user_id": "test-user"}).json()[
            "session_id"
        ]
        client.post(
            "/api/dashboard/chat", json={"session_id": session_id, "message": "Deploy Kuma"}
        )
        response = client.post(
            "/api/dashboard/plan/plan-123/approve", json={"session_id": session_id}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "approved"

    def test_reject_plan_cancels(
        self, client: TestClient, orchestrator_stub: OrchestratorStub
    ) -> None:
        session_id = client.post("/api/dashboard/session", json={"user_id": "test-user"}).json()[
            "session_id"
        ]
        response = client.post(
            "/api/dashboard/plan/plan-123/reject", json={"session_id": session_id}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "rejected"

    def test_modify_plan_returns_new_plan(
        self, client: TestClient, orchestrator_stub: OrchestratorStub
    ) -> None:
        session_id = client.post("/api/dashboard/session", json={"user_id": "test-user"}).json()[
            "session_id"
        ]
        response = client.post(
            "/api/dashboard/plan/plan-123/modify",
            json={
                "plan_id": "plan-123",
                "session_id": session_id,
                "user_message": "Use staging",
            },
        )
        assert response.status_code == 200
        assert "new_plan" in response.json()


class TestExecutionMonitoring:
    def test_get_execution_status(
        self, client: TestClient, orchestrator_stub: OrchestratorStub
    ) -> None:
        response = client.get("/api/dashboard/plan/plan-123/poll")
        assert response.status_code == 200
        data = response.json()
        assert "steps" in data

    def test_abort_cancels_execution(
        self, client: TestClient, orchestrator_stub: OrchestratorStub
    ) -> None:
        session_id = client.post("/api/dashboard/session", json={"user_id": "test-user"}).json()[
            "session_id"
        ]
        client.post(
            "/api/dashboard/chat", json={"session_id": session_id, "message": "Deploy Kuma"}
        )
        client.post("/api/dashboard/plan/plan-123/approve", json={"session_id": session_id})
        response = client.post(
            "/api/dashboard/plan/plan-123/abort", json={"session_id": session_id}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "aborted"


class TestRequirementVerification:
    @pytest.mark.ui_requirement("UI-01")
    def test_ui_01_chat_interface_accepts_requests(
        self, client: TestClient, orchestrator_stub: OrchestratorStub
    ) -> None:
        session_id = client.post("/api/dashboard/session", json={"user_id": "test-user"}).json()[
            "session_id"
        ]
        response = client.post(
            "/api/dashboard/chat",
            json={
                "session_id": session_id,
                "message": "Deploy Kuma to my homelab with portal configs",
            },
        )
        assert response.status_code == 200

    @pytest.mark.ui_requirement("UI-02")
    def test_ui_02_plan_presentation(
        self, client: TestClient, orchestrator_stub: OrchestratorStub
    ) -> None:
        session_id = client.post("/api/dashboard/session", json={"user_id": "test-user"}).json()[
            "session_id"
        ]
        chat_response = client.post(
            "/api/dashboard/chat",
            json={"session_id": session_id, "message": "Deploy Kuma"},
        )
        plan_id = chat_response.json()["plan"]["plan_id"]
        response = client.get(f"/api/dashboard/plan/{plan_id}")
        assert response.status_code == 200
        assert "summary" in response.json()

    @pytest.mark.ui_requirement("UI-03")
    def test_ui_03_approval_workflow(
        self, client: TestClient, orchestrator_stub: OrchestratorStub
    ) -> None:
        session_id = client.post("/api/dashboard/session", json={"user_id": "test-user"}).json()[
            "session_id"
        ]
        approve = client.post(
            "/api/dashboard/plan/plan-123/approve", json={"session_id": session_id}
        )
        assert approve.status_code == 200
        reject = client.post("/api/dashboard/plan/plan-123/reject", json={"session_id": session_id})
        assert reject.status_code == 200
        modify = client.post(
            "/api/dashboard/plan/plan-123/modify",
            json={
                "plan_id": "plan-123",
                "session_id": session_id,
                "user_message": "Use staging first",
            },
        )
        assert modify.status_code == 200

    @pytest.mark.ui_requirement("UI-04")
    def test_ui_04_execution_log_transparency(
        self, client: TestClient, orchestrator_stub: OrchestratorStub
    ) -> None:
        response = client.get("/api/dashboard/plan/plan-123/poll")
        assert response.status_code == 200
        assert "steps" in response.json()


class TestFullWorkflow:
    def test_complete_workflow(
        self, client: TestClient, orchestrator_stub: OrchestratorStub
    ) -> None:
        session_id = client.post("/api/dashboard/session", json={"user_id": "test-user"}).json()[
            "session_id"
        ]
        chat_response = client.post(
            "/api/dashboard/chat",
            json={"session_id": session_id, "message": "Deploy Kuma monitoring"},
        )
        plan_id = chat_response.json()["plan"]["plan_id"]
        assert client.get(f"/api/dashboard/plan/{plan_id}").status_code == 200
        assert (
            client.post(
                f"/api/dashboard/plan/{plan_id}/approve", json={"session_id": session_id}
            ).status_code
            == 200
        )
        status = client.get(f"/api/dashboard/plan/{plan_id}/poll")
        assert status.status_code == 200
        assert status.json()["overall_status"] in {"executing", "pending_approval", "completed"}
