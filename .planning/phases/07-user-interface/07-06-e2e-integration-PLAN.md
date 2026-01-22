# Phase 7 Plan 06: E2E Integration Tests

---
phase: 07-user-interface
plan: 06
type: execute
wave: 3
depends_on: ["07-01", "07-02", "07-03", "07-04", "07-05"]
files_modified:
  - tests/test_ui_e2e.py
  - tests/test_ui_orchestrator_integration.py
  - docker-compose.yml
  - src/dashboard/__init__.py
  - docs/UI-SETUP.md
autonomous: true
must_haves:
  truths:
    - "Full workflow tested: chat -> plan -> approve -> execute -> summary"
    - "All UI requirements (UI-01 through UI-04) verified"
    - "Integration with orchestrator API verified"
    - "WebSocket real-time updates verified"
    - "Docker compose includes dashboard service"
  artifacts:
    - path: "tests/test_ui_e2e.py"
      provides: "End-to-end UI workflow tests"
    - path: "tests/test_ui_orchestrator_integration.py"
      provides: "UI-Orchestrator integration tests"
    - path: "docs/UI-SETUP.md"
      provides: "UI setup documentation"
  key_links:
    - from: "tests/test_ui_e2e.py"
      to: "src/dashboard/api.py"
      via: "HTTP requests"
      pattern: "TestClient"
    - from: "docker-compose.yml"
      to: "src/dashboard/main.py"
      via: "service definition"
      pattern: "dashboard"
---

<objective>
Create comprehensive end-to-end integration tests that verify the complete UI workflow from chat input through execution summary. Validates all UI requirements (UI-01 through UI-04) and ensures proper integration with the orchestrator.

Purpose: E2E tests catch integration issues that unit tests miss. This plan validates the entire Phase 7 works together and with the orchestrator, ensuring the system is ready for Phase 8 end-to-end validation.

Output: Complete test suite, docker-compose integration, and setup documentation for the dashboard.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@src/dashboard/api.py
@src/dashboard/websocket.py
@src/orchestrator/api.py
@docker-compose.yml
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create E2E workflow tests</name>
  <files>
    tests/test_ui_e2e.py
  </files>
  <action>
Create comprehensive end-to-end tests for the UI workflow:

1. Create tests/test_ui_e2e.py:

```python
"""End-to-end tests for UI workflow.

Tests the complete workflow: chat -> plan -> approve -> execute -> summary.
All UI requirements (UI-01 through UI-04) are verified.
"""

import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch

from src.dashboard.main import app
from src.dashboard.models import ChatSession, ChatMessage, DashboardPlanView


@pytest.fixture
def test_client():
    """Create test client for dashboard API."""
    return TestClient(app)


@pytest.fixture
def mock_orchestrator():
    """Mock orchestrator API responses."""
    with patch("src.dashboard.api.httpx.AsyncClient") as mock:
        client = AsyncMock()
        mock.return_value.__aenter__.return_value = client

        # Default responses
        client.post.return_value = AsyncMock(
            status_code=200,
            json=lambda: {"request_id": "test-request-123", "status": "parsing_complete"}
        )
        client.get.return_value = AsyncMock(
            status_code=200,
            json=lambda: {
                "plan_id": "test-plan-123",
                "request_id": "test-request-123",
                "tasks": [{"name": "Step 1", "work_type": "deploy_service"}],
                "human_readable_summary": "Deploy Kuma to homelab",
                "complexity_level": "simple",
                "will_use_external_ai": False,
                "status": "pending_approval",
            }
        )

        yield client


class TestChatWorkflow:
    """Test chat interface functionality (UI-01)."""

    def test_create_session(self, test_client):
        """Test session creation."""
        response = test_client.post(
            "/api/dashboard/session",
            json={"user_id": "test-user"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert data["status"] == "idle"

    def test_send_deployment_request(self, test_client, mock_orchestrator):
        """Test sending deployment request via chat (UI-01)."""
        # Create session first
        session_response = test_client.post(
            "/api/dashboard/session",
            json={"user_id": "test-user"}
        )
        session_id = session_response.json()["session_id"]

        # Send deployment request
        response = test_client.post(
            "/api/dashboard/chat",
            json={
                "session_id": session_id,
                "message": "Deploy Kuma Uptime monitoring to homelab"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "messages" in data
        assert len(data["messages"]) >= 2  # User message + assistant response

    def test_chat_handles_modification_request(self, test_client, mock_orchestrator):
        """Test modification request via chat (UI-03)."""
        # Setup: create session, send initial request, get plan
        session_response = test_client.post(
            "/api/dashboard/session",
            json={"user_id": "test-user"}
        )
        session_id = session_response.json()["session_id"]

        test_client.post(
            "/api/dashboard/chat",
            json={"session_id": session_id, "message": "Deploy Kuma"}
        )

        # Send modification request
        response = test_client.post(
            "/api/dashboard/chat",
            json={
                "session_id": session_id,
                "message": "Use staging environment instead"
            }
        )

        assert response.status_code == 200


class TestPlanReviewWorkflow:
    """Test plan presentation and approval (UI-02, UI-03)."""

    def test_get_plan_formatted_for_ui(self, test_client, mock_orchestrator):
        """Test plan is formatted for UI display (UI-02)."""
        # Setup session and get plan
        session_response = test_client.post(
            "/api/dashboard/session",
            json={"user_id": "test-user"}
        )
        session_id = session_response.json()["session_id"]

        chat_response = test_client.post(
            "/api/dashboard/chat",
            json={"session_id": session_id, "message": "Deploy Kuma"}
        )

        plan_id = chat_response.json().get("plan", {}).get("plan_id")
        if plan_id:
            response = test_client.get(f"/api/dashboard/plan/{plan_id}")
            assert response.status_code == 200
            data = response.json()

            # Verify UI-02: plan presentation format
            assert "summary" in data
            assert "steps" in data
            assert "estimated_duration" in data
            assert "risk_level" in data

    def test_approve_plan_triggers_execution(self, test_client, mock_orchestrator):
        """Test approve button triggers execution (UI-03)."""
        # Setup
        session_response = test_client.post(
            "/api/dashboard/session",
            json={"user_id": "test-user"}
        )
        session_id = session_response.json()["session_id"]

        mock_orchestrator.post.return_value = AsyncMock(
            status_code=200,
            json=lambda: {"status": "approved", "dispatch_started": True}
        )

        # Approve plan
        response = test_client.post(
            "/api/dashboard/plan/test-plan-123/approve"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"

    def test_reject_plan_cancels(self, test_client, mock_orchestrator):
        """Test reject button cancels plan (UI-03)."""
        mock_orchestrator.post.return_value = AsyncMock(
            status_code=200,
            json=lambda: {"status": "rejected"}
        )

        response = test_client.post(
            "/api/dashboard/plan/test-plan-123/reject"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"

    def test_modify_plan_returns_new_plan(self, test_client, mock_orchestrator):
        """Test modify returns updated plan (UI-03)."""
        mock_orchestrator.post.return_value = AsyncMock(
            status_code=200,
            json=lambda: {
                "new_plan": {
                    "plan_id": "test-plan-124",
                    "summary": "Deploy Kuma to staging",
                    "steps": [],
                    "status": "pending_approval",
                }
            }
        )

        response = test_client.post(
            "/api/dashboard/plan/test-plan-123/modify",
            json={
                "plan_id": "test-plan-123",
                "session_id": "test-session",
                "user_message": "Use staging environment"
            }
        )

        assert response.status_code == 200


class TestExecutionMonitoring:
    """Test execution log and real-time updates (UI-04)."""

    def test_get_execution_status(self, test_client, mock_orchestrator):
        """Test execution status polling (UI-04)."""
        mock_orchestrator.get.return_value = AsyncMock(
            status_code=200,
            json=lambda: {
                "plan_id": "test-plan-123",
                "status": "executing",
                "steps": [
                    {"index": 0, "name": "Step 1", "status": "completed"},
                    {"index": 1, "name": "Step 2", "status": "running"},
                ]
            }
        )

        response = test_client.get("/api/dashboard/plan/test-plan-123/poll")

        assert response.status_code == 200
        data = response.json()
        assert "steps" in data

    def test_abort_cancels_execution(self, test_client, mock_orchestrator):
        """Test abort stops execution (UI-04)."""
        mock_orchestrator.post.return_value = AsyncMock(
            status_code=200,
            json=lambda: {"status": "aborted"}
        )

        response = test_client.post("/api/dashboard/plan/test-plan-123/abort")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "aborted"


class TestRequirementVerification:
    """Explicit tests for each UI requirement."""

    @pytest.mark.ui_requirement("UI-01")
    def test_UI_01_chat_interface_accepts_requests(self, test_client, mock_orchestrator):
        """UI-01: Chat interface accepts deployment requests in natural language."""
        # Create session
        session_response = test_client.post(
            "/api/dashboard/session",
            json={"user_id": "test-user"}
        )
        assert session_response.status_code == 200
        session_id = session_response.json()["session_id"]

        # Send natural language request
        response = test_client.post(
            "/api/dashboard/chat",
            json={
                "session_id": session_id,
                "message": "Deploy Kuma Uptime monitoring to my homelab with the existing portal configs"
            }
        )
        assert response.status_code == 200

        # Verify request received by orchestrator (via mock)
        mock_orchestrator.post.assert_called()

    @pytest.mark.ui_requirement("UI-02")
    def test_UI_02_plan_presentation_format(self, test_client, mock_orchestrator):
        """UI-02: Orchestrator presents execution plan to user for approval."""
        # Get plan
        mock_orchestrator.get.return_value = AsyncMock(
            status_code=200,
            json=lambda: {
                "plan_id": "test-plan",
                "request_id": "test-request",
                "tasks": [
                    {"order": 1, "name": "Check prerequisites", "work_type": "shell_script"},
                    {"order": 2, "name": "Deploy container", "work_type": "docker"},
                ],
                "human_readable_summary": "Deploy Kuma with 2 steps",
                "complexity_level": "simple",
                "will_use_external_ai": False,
                "status": "pending_approval",
            }
        )

        response = test_client.get("/api/dashboard/plan/test-plan")
        assert response.status_code == 200
        data = response.json()

        # Verify format requirements
        assert "summary" in data  # Human-readable summary
        assert "steps" in data  # Step-by-step list
        assert "estimated_duration" in data  # Duration estimate
        assert "risk_level" in data  # Risk assessment

    @pytest.mark.ui_requirement("UI-03")
    def test_UI_03_approval_workflow(self, test_client, mock_orchestrator):
        """UI-03: User can approve, reject, or request modifications."""
        # Test approve
        mock_orchestrator.post.return_value = AsyncMock(
            status_code=200,
            json=lambda: {"status": "approved", "dispatch_started": True}
        )
        approve_response = test_client.post("/api/dashboard/plan/test-plan/approve")
        assert approve_response.status_code == 200
        assert approve_response.json()["status"] == "approved"

        # Test reject
        mock_orchestrator.post.return_value = AsyncMock(
            status_code=200,
            json=lambda: {"status": "rejected"}
        )
        reject_response = test_client.post("/api/dashboard/plan/test-plan/reject")
        assert reject_response.status_code == 200
        assert reject_response.json()["status"] == "rejected"

        # Test modify
        mock_orchestrator.post.return_value = AsyncMock(
            status_code=200,
            json=lambda: {"new_plan": {"plan_id": "test-plan-2"}}
        )
        modify_response = test_client.post(
            "/api/dashboard/plan/test-plan/modify",
            json={
                "plan_id": "test-plan",
                "session_id": "test-session",
                "user_message": "Use staging Kuma first"
            }
        )
        assert modify_response.status_code == 200

    @pytest.mark.ui_requirement("UI-04")
    def test_UI_04_execution_log_transparency(self, test_client, mock_orchestrator):
        """UI-04: Execution log shows all steps, outputs, and decisions."""
        mock_orchestrator.get.return_value = AsyncMock(
            status_code=200,
            json=lambda: {
                "plan_id": "test-plan",
                "status": "executing",
                "steps": [
                    {
                        "index": 0,
                        "name": "Check prerequisites",
                        "status": "completed",
                        "output": "All prerequisites met",
                        "duration_ms": 1500,
                    },
                    {
                        "index": 1,
                        "name": "Deploy container",
                        "status": "running",
                    },
                ]
            }
        )

        response = test_client.get("/api/dashboard/plan/test-plan/poll")
        assert response.status_code == 200
        data = response.json()

        # Verify transparency requirements
        assert "steps" in data
        steps = data["steps"]
        assert len(steps) > 0
        assert "status" in steps[0]  # Step status visible
        assert "output" in steps[0]  # Output visible


class TestFullWorkflow:
    """Test complete end-to-end workflow."""

    def test_complete_workflow_chat_to_summary(self, test_client, mock_orchestrator):
        """Test full workflow: chat -> plan -> approve -> execute -> summary."""
        # 1. Create session
        session_response = test_client.post(
            "/api/dashboard/session",
            json={"user_id": "test-user"}
        )
        assert session_response.status_code == 200
        session_id = session_response.json()["session_id"]

        # 2. Submit deployment request via chat
        mock_orchestrator.post.return_value = AsyncMock(
            status_code=200,
            json=lambda: {"request_id": "req-123", "status": "parsing_complete"}
        )
        mock_orchestrator.get.return_value = AsyncMock(
            status_code=200,
            json=lambda: {
                "plan_id": "plan-123",
                "request_id": "req-123",
                "tasks": [{"name": "Deploy Kuma"}],
                "human_readable_summary": "Deploy Kuma monitoring",
                "complexity_level": "simple",
                "will_use_external_ai": False,
                "status": "pending_approval",
            }
        )

        chat_response = test_client.post(
            "/api/dashboard/chat",
            json={
                "session_id": session_id,
                "message": "Deploy Kuma Uptime monitoring"
            }
        )
        assert chat_response.status_code == 200

        # 3. Review plan
        plan_response = test_client.get("/api/dashboard/plan/plan-123")
        assert plan_response.status_code == 200

        # 4. Approve plan
        mock_orchestrator.post.return_value = AsyncMock(
            status_code=200,
            json=lambda: {"status": "approved", "dispatch_started": True}
        )

        approve_response = test_client.post("/api/dashboard/plan/plan-123/approve")
        assert approve_response.status_code == 200
        assert approve_response.json()["status"] == "approved"

        # 5. Monitor execution (poll)
        mock_orchestrator.get.return_value = AsyncMock(
            status_code=200,
            json=lambda: {
                "plan_id": "plan-123",
                "status": "completed",
                "steps": [{"index": 0, "name": "Deploy Kuma", "status": "completed"}],
            }
        )

        status_response = test_client.get("/api/dashboard/plan/plan-123/poll")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "completed"
```
  </action>
  <verify>
    - [ ] All E2E tests pass: `pytest tests/test_ui_e2e.py -v`
    - [ ] UI-01 through UI-04 requirements explicitly tested
    - [ ] Full workflow tested end-to-end
    - [ ] Tests use mocks (no real orchestrator needed)
  </verify>
  <done>E2E workflow tests created covering all UI requirements</done>
</task>

<task type="auto">
  <name>Task 2: Create orchestrator integration tests</name>
  <files>
    tests/test_ui_orchestrator_integration.py
  </files>
  <action>
Create integration tests verifying dashboard works with real orchestrator:

1. Create tests/test_ui_orchestrator_integration.py:

```python
"""Integration tests for Dashboard <-> Orchestrator communication.

These tests verify the dashboard correctly proxies to the orchestrator
and handles responses appropriately.

Note: These tests require a running orchestrator instance or use
extensive mocking to simulate orchestrator behavior.
"""

import asyncio
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock

from src.dashboard.main import app
from src.dashboard.api import _format_plan_for_dashboard


@pytest.fixture
def test_client():
    """Create test client."""
    return TestClient(app)


class TestDashboardOrchestratorProxy:
    """Test dashboard correctly proxies to orchestrator."""

    def test_chat_proxies_to_orchestrator_request_endpoint(self, test_client):
        """Dashboard chat calls orchestrator POST /api/v1/request."""
        with patch("src.dashboard.api.httpx.AsyncClient") as mock:
            client = AsyncMock()
            mock.return_value.__aenter__.return_value = client
            client.post.return_value = AsyncMock(
                status_code=200,
                json=lambda: {"request_id": "req-123", "status": "parsing_complete"}
            )
            client.get.return_value = AsyncMock(
                status_code=200,
                json=lambda: {"plan_id": "plan-123", "status": "pending_approval"}
            )

            # Create session first
            session_response = test_client.post(
                "/api/dashboard/session",
                json={"user_id": "test-user"}
            )
            session_id = session_response.json()["session_id"]

            # Send chat
            test_client.post(
                "/api/dashboard/chat",
                json={"session_id": session_id, "message": "Deploy Kuma"}
            )

            # Verify orchestrator was called
            assert client.post.called
            call_args = client.post.call_args
            assert "/api/v1/request" in str(call_args)

    def test_plan_approval_proxies_correctly(self, test_client):
        """Dashboard approval calls orchestrator POST /api/v1/plan/{id}/approve."""
        with patch("src.dashboard.api.httpx.AsyncClient") as mock:
            client = AsyncMock()
            mock.return_value.__aenter__.return_value = client
            client.post.return_value = AsyncMock(
                status_code=200,
                json=lambda: {"status": "approved", "dispatch_started": True}
            )

            test_client.post("/api/dashboard/plan/test-plan/approve")

            assert client.post.called
            call_args = client.post.call_args
            assert "/approve" in str(call_args)

    def test_plan_rejection_proxies_correctly(self, test_client):
        """Dashboard rejection calls orchestrator with approved=false."""
        with patch("src.dashboard.api.httpx.AsyncClient") as mock:
            client = AsyncMock()
            mock.return_value.__aenter__.return_value = client
            client.post.return_value = AsyncMock(
                status_code=200,
                json=lambda: {"status": "rejected"}
            )

            test_client.post("/api/dashboard/plan/test-plan/reject")

            assert client.post.called


class TestPlanFormatting:
    """Test plan formatting for dashboard display."""

    def test_format_plan_adds_risk_level(self):
        """Risk level derived from complexity."""
        # Simple -> low
        simple_plan = {
            "plan_id": "p1",
            "complexity_level": "simple",
            "tasks": [],
            "human_readable_summary": "Test",
        }
        formatted = _format_plan_for_dashboard(simple_plan)
        assert formatted["risk_level"] == "low"

        # Medium -> medium
        medium_plan = {**simple_plan, "complexity_level": "medium"}
        formatted = _format_plan_for_dashboard(medium_plan)
        assert formatted["risk_level"] == "medium"

        # Complex -> high
        complex_plan = {**simple_plan, "complexity_level": "complex"}
        formatted = _format_plan_for_dashboard(complex_plan)
        assert formatted["risk_level"] == "high"

    def test_format_plan_adds_duration_estimate(self):
        """Duration formatted as human-readable string."""
        plan = {
            "plan_id": "p1",
            "complexity_level": "simple",
            "tasks": [
                {"resource_requirements": {"estimated_duration_seconds": 60}},
                {"resource_requirements": {"estimated_duration_seconds": 120}},
            ],
            "human_readable_summary": "Test",
        }
        formatted = _format_plan_for_dashboard(plan)
        assert "estimated_duration" in formatted
        # Should be something like "~3 minutes"

    def test_format_plan_converts_steps_to_checklist(self):
        """Tasks converted to step checklist format."""
        plan = {
            "plan_id": "p1",
            "complexity_level": "simple",
            "tasks": [
                {"order": 1, "name": "Step 1", "work_type": "shell"},
                {"order": 2, "name": "Step 2", "work_type": "docker"},
            ],
            "human_readable_summary": "Test",
        }
        formatted = _format_plan_for_dashboard(plan)
        assert "steps" in formatted
        assert len(formatted["steps"]) == 2
        assert formatted["steps"][0]["name"] == "Step 1"


class TestErrorHandling:
    """Test error handling in dashboard-orchestrator communication."""

    def test_orchestrator_timeout_handled(self, test_client):
        """Dashboard handles orchestrator timeout gracefully."""
        with patch("src.dashboard.api.httpx.AsyncClient") as mock:
            client = AsyncMock()
            mock.return_value.__aenter__.return_value = client
            client.post.side_effect = asyncio.TimeoutError()

            session_response = test_client.post(
                "/api/dashboard/session",
                json={"user_id": "test-user"}
            )
            session_id = session_response.json()["session_id"]

            response = test_client.post(
                "/api/dashboard/chat",
                json={"session_id": session_id, "message": "Deploy Kuma"}
            )

            # Should return error, not crash
            assert response.status_code in [500, 504]

    def test_orchestrator_error_response_handled(self, test_client):
        """Dashboard handles orchestrator error responses."""
        with patch("src.dashboard.api.httpx.AsyncClient") as mock:
            client = AsyncMock()
            mock.return_value.__aenter__.return_value = client
            client.get.return_value = AsyncMock(
                status_code=404,
                json=lambda: {"detail": "Plan not found"}
            )

            response = test_client.get("/api/dashboard/plan/nonexistent-plan")

            assert response.status_code == 404


class TestWebSocketIntegration:
    """Test WebSocket communication with dashboard."""

    def test_websocket_connection_established(self, test_client):
        """WebSocket accepts connection with session ID."""
        with test_client.websocket_connect("/ws/test-session-123") as ws:
            # Send ping
            ws.send_json({"type": "ping"})
            response = ws.receive_json()
            assert response["type"] == "pong"

    def test_websocket_subscribe_to_plan(self, test_client):
        """Client can subscribe to plan updates."""
        with test_client.websocket_connect("/ws/test-session-123") as ws:
            ws.send_json({"type": "subscribe", "plan_id": "test-plan-123"})
            response = ws.receive_json()
            assert response["type"] == "subscribed"
            assert response["plan_id"] == "test-plan-123"

    def test_websocket_unsubscribe_from_plan(self, test_client):
        """Client can unsubscribe from plan updates."""
        with test_client.websocket_connect("/ws/test-session-123") as ws:
            # Subscribe first
            ws.send_json({"type": "subscribe", "plan_id": "test-plan-123"})
            ws.receive_json()

            # Unsubscribe
            ws.send_json({"type": "unsubscribe", "plan_id": "test-plan-123"})
            response = ws.receive_json()
            assert response["type"] == "unsubscribed"
```
  </action>
  <verify>
    - [ ] All integration tests pass: `pytest tests/test_ui_orchestrator_integration.py -v`
    - [ ] Proxy behavior verified (dashboard calls correct orchestrator endpoints)
    - [ ] Plan formatting tested (risk level, duration, steps)
    - [ ] Error handling tested (timeouts, error responses)
    - [ ] WebSocket integration tested
  </verify>
  <done>Orchestrator integration tests created</done>
</task>

<task type="auto">
  <name>Task 3: Update docker-compose and create documentation</name>
  <files>
    docker-compose.yml
    src/dashboard/__init__.py
    docs/UI-SETUP.md
  </files>
  <action>
Add dashboard service to docker-compose and create setup documentation:

1. Update docker-compose.yml to add dashboard service:

   Add after orchestrator service:
   ```yaml
   dashboard:
     build:
       context: .
       dockerfile: Dockerfile.dashboard
     container_name: chiffon-dashboard
     ports:
       - "8001:8001"
     environment:
       - ORCHESTRATOR_URL=http://orchestrator:8000
       - LOG_LEVEL=INFO
     depends_on:
       - orchestrator
       - rabbitmq
     volumes:
       - ./src:/app/src:ro
     healthcheck:
       test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
       interval: 30s
       timeout: 10s
       retries: 3
     networks:
       - chiffon-network
   ```

2. Create Dockerfile.dashboard:
   ```dockerfile
   FROM python:3.11-slim

   WORKDIR /app

   # Install dependencies
   COPY pyproject.toml poetry.lock ./
   RUN pip install poetry && poetry install --no-root --only main

   # Copy source
   COPY src/ ./src/

   # Expose port
   EXPOSE 8001

   # Run dashboard
   CMD ["poetry", "run", "uvicorn", "src.dashboard.main:app", "--host", "0.0.0.0", "--port", "8001"]
   ```

3. Update src/dashboard/__init__.py with complete exports:
   ```python
   """Chiffon Dashboard API.

   Provides:
   - REST API for chat, plan review, and execution monitoring
   - WebSocket real-time updates
   - Session management

   Services:
   - dashboard_router: FastAPI router with all endpoints
   - ws_router: WebSocket endpoint router
   - ws_manager: WebSocket connection manager

   Models:
   - ChatSession: Chat session with message history
   - ChatMessage: Individual chat message
   - DashboardPlanView: UI-formatted plan display
   """

   from .api import router as dashboard_router
   from .websocket import ws_router, ws_manager
   from .models import (
       ChatSession,
       ChatMessage,
       DashboardPlanView,
       ModificationRequest,
       ExecutionUpdate,
       SessionStore,
   )

   __all__ = [
       "dashboard_router",
       "ws_router",
       "ws_manager",
       "ChatSession",
       "ChatMessage",
       "DashboardPlanView",
       "ModificationRequest",
       "ExecutionUpdate",
       "SessionStore",
   ]
   ```

4. Create docs/UI-SETUP.md:
   ```markdown
   # Chiffon Dashboard Setup

   ## Overview

   The Chiffon Dashboard provides a web interface for:
   - Submitting deployment requests via natural language chat
   - Reviewing and approving execution plans
   - Monitoring real-time execution progress
   - Viewing execution summaries and audit trails

   ## Architecture

   ```
   +-------------+     +-------------+     +---------------+
   |   Browser   | <-> |  Dashboard  | <-> | Orchestrator  |
   |  (React)    |     |  (FastAPI)  |     |   (FastAPI)   |
   +-------------+     +-------------+     +---------------+
         |                   |
         |  WebSocket        |  HTTP
         +-------------------+
   ```

   ## Quick Start

   ### Using Docker Compose

   ```bash
   # Start all services including dashboard
   docker-compose up -d

   # Dashboard available at http://localhost:8001
   # Frontend available at http://localhost:3000
   ```

   ### Manual Setup

   **Backend (Dashboard API):**
   ```bash
   # Install dependencies
   poetry install

   # Start dashboard
   poetry run uvicorn src.dashboard.main:app --port 8001
   ```

   **Frontend (React):**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

   ## Configuration

   ### Environment Variables

   | Variable | Default | Description |
   |----------|---------|-------------|
   | `ORCHESTRATOR_URL` | `http://localhost:8000` | Orchestrator API URL |
   | `LOG_LEVEL` | `INFO` | Logging level |
   | `SESSION_TTL_HOURS` | `24` | Chat session TTL |

   ### Frontend Configuration

   Edit `frontend/vite.config.ts` to configure API proxy:
   ```typescript
   proxy: {
     '/api': {
       target: 'http://localhost:8001',  // Dashboard API
     },
     '/ws': {
       target: 'ws://localhost:8001',    // WebSocket
       ws: true,
     },
   }
   ```

   ## API Endpoints

   ### Chat & Sessions

   | Method | Endpoint | Description |
   |--------|----------|-------------|
   | POST | `/api/dashboard/session` | Create chat session |
   | GET | `/api/dashboard/session/{id}` | Get session with history |
   | POST | `/api/dashboard/chat` | Send chat message |

   ### Plan Operations

   | Method | Endpoint | Description |
   |--------|----------|-------------|
   | GET | `/api/dashboard/plan/{id}` | Get plan for review |
   | POST | `/api/dashboard/plan/{id}/approve` | Approve plan |
   | POST | `/api/dashboard/plan/{id}/reject` | Reject plan |
   | POST | `/api/dashboard/plan/{id}/modify` | Request modifications |
   | GET | `/api/dashboard/plan/{id}/poll` | Poll execution status |
   | POST | `/api/dashboard/plan/{id}/abort` | Abort execution |

   ### WebSocket

   Connect to `/ws/{session_id}` for real-time updates.

   **Message Types:**
   - `subscribe`: Subscribe to plan updates
   - `unsubscribe`: Unsubscribe from plan
   - `ping`: Keepalive ping

   **Server Messages:**
   - `step_status`: Step status change
   - `step_output`: Step output chunk
   - `plan_completed`: Execution complete
   - `plan_failed`: Execution failed

   ## Testing

   ```bash
   # Run all UI tests
   pytest tests/test_ui_*.py -v

   # Run frontend tests
   cd frontend && npm test

   # Run E2E tests
   pytest tests/test_ui_e2e.py -v
   ```

   ## Troubleshooting

   ### WebSocket Connection Failed

   1. Check dashboard is running on port 8001
   2. Verify CORS settings allow WebSocket upgrade
   3. Check browser console for connection errors

   ### Chat Not Receiving Response

   1. Verify orchestrator is running on port 8000
   2. Check ORCHESTRATOR_URL environment variable
   3. Review dashboard logs for proxy errors

   ### Plan Not Displaying

   1. Verify plan_id is valid
   2. Check orchestrator has the plan
   3. Review dashboard formatting logic

   ## Requirements Satisfied

   - **UI-01**: Chat interface accepts deployment requests in natural language
   - **UI-02**: Orchestrator presents execution plan to user for approval
   - **UI-03**: User can approve, reject, or request modifications
   - **UI-04**: Execution log shows all steps, outputs, and decisions
   ```
  </action>
  <verify>
    - [ ] docker-compose.yml includes dashboard service
    - [ ] `docker-compose up dashboard` starts successfully
    - [ ] Dashboard health check passes
    - [ ] UI-SETUP.md created with complete documentation
    - [ ] All exports in __init__.py work
  </verify>
  <done>Docker integration and documentation created</done>
</task>

</tasks>

<verification>
After all tasks complete:
1. Run all UI tests: `pytest tests/test_ui_*.py -v`
2. Start with docker: `docker-compose up -d`
3. Verify dashboard health: `curl http://localhost:8001/health`
4. Run frontend: `cd frontend && npm run dev`
5. Test full workflow manually
</verification>

<success_criteria>
- All E2E tests pass covering chat -> plan -> approve -> execute -> summary
- UI-01 through UI-04 explicitly verified with tests
- Dashboard service runs in docker-compose
- WebSocket integration tests pass
- Error handling comprehensive
- Documentation complete
- Total test count for Phase 7: 80+ tests
</success_criteria>

<output>
After completion, create `.planning/phases/07-user-interface/07-06-SUMMARY.md`
</output>
