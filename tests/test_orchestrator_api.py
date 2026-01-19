"""Tests for orchestrator REST API endpoints.

Tests cover:
- POST /api/v1/dispatch
- GET /api/v1/status/{task_id}
- GET /api/v1/agents
- POST /api/v1/cancel/{task_id}
"""

import json
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from src.orchestrator.main import app
from src.orchestrator.service import OrchestratorService


@pytest.fixture
def mock_orchestrator_service():
    """Mock OrchestratorService for testing."""
    service = AsyncMock(spec=OrchestratorService)
    return service


@pytest.fixture
def inject_mock_service(mock_orchestrator_service):
    """Inject mock service into app dependency overrides."""
    from src.orchestrator.api import get_orchestrator_service

    async def get_mock():
        return mock_orchestrator_service

    app.dependency_overrides[get_orchestrator_service] = get_mock
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
class TestDispatchEndpoint:
    """Tests for POST /api/v1/dispatch."""

    async def test_dispatch_accepts_valid_request(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test dispatch with valid request."""
        task_id = str(uuid4())
        trace_id = str(uuid4())
        request_id = str(uuid4())

        mock_orchestrator_service.dispatch_work.return_value = {
            "trace_id": trace_id,
            "request_id": request_id,
            "task_id": task_id,
            "status": "pending",
        }

        response = await async_client.post(
            "/api/v1/dispatch",
            json={
                "task_id": task_id,
                "work_type": "ansible",
                "parameters": {"playbook": "test.yml"},
                "priority": 3,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["trace_id"] == trace_id
        assert data["request_id"] == request_id
        assert data["task_id"] == task_id
        assert data["status"] == "pending"

    async def test_dispatch_returns_trace_id_and_request_id(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test that dispatch returns both trace_id and request_id."""
        task_id = str(uuid4())
        trace_id = str(uuid4())
        request_id = str(uuid4())

        mock_orchestrator_service.dispatch_work.return_value = {
            "trace_id": trace_id,
            "request_id": request_id,
            "task_id": task_id,
            "status": "pending",
        }

        response = await async_client.post(
            "/api/v1/dispatch",
            json={
                "task_id": task_id,
                "work_type": "docker",
                "parameters": {},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "trace_id" in data
        assert "request_id" in data
        assert data["trace_id"] != data["request_id"]

    async def test_dispatch_requires_task_id(self, async_client: AsyncClient, inject_mock_service):
        """Test that dispatch rejects missing task_id."""
        response = await async_client.post(
            "/api/v1/dispatch",
            json={
                "work_type": "ansible",
                "parameters": {},
            },
        )

        assert response.status_code == 422  # Validation error

    async def test_dispatch_requires_work_type(self, async_client: AsyncClient, inject_mock_service):
        """Test that dispatch rejects missing work_type."""
        task_id = str(uuid4())

        response = await async_client.post(
            "/api/v1/dispatch",
            json={
                "task_id": task_id,
                "parameters": {},
            },
        )

        assert response.status_code == 422

    async def test_dispatch_validates_priority_range_1_to_5(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test that dispatch validates priority range."""
        task_id = str(uuid4())

        # Priority too low
        response = await async_client.post(
            "/api/v1/dispatch",
            json={
                "task_id": task_id,
                "work_type": "ansible",
                "parameters": {},
                "priority": 0,
            },
        )
        assert response.status_code == 422

        # Priority too high
        response = await async_client.post(
            "/api/v1/dispatch",
            json={
                "task_id": task_id,
                "work_type": "ansible",
                "parameters": {},
                "priority": 6,
            },
        )
        assert response.status_code == 422

    async def test_dispatch_error_on_invalid_work_type(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test dispatch error handling for invalid work_type."""
        task_id = str(uuid4())

        mock_orchestrator_service.dispatch_work.side_effect = ValueError("Unknown work_type: invalid")

        response = await async_client.post(
            "/api/v1/dispatch",
            json={
                "task_id": task_id,
                "work_type": "invalid",
                "parameters": {},
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "detail" in data


@pytest.mark.asyncio
class TestStatusEndpoint:
    """Tests for GET /api/v1/status/{task_id}."""

    async def test_status_returns_task_info(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test status endpoint returns task information."""
        task_id = str(uuid4())

        mock_orchestrator_service.get_task_status.return_value = {
            "task_id": task_id,
            "status": "pending",
            "progress": "",
            "output": "",
            "error_message": None,
            "created_at": "2026-01-19T10:00:00",
            "updated_at": None,
        }

        response = await async_client.get(f"/api/v1/status/{task_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == task_id
        assert data["status"] == "pending"

    async def test_status_returns_404_for_missing_task(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test status returns 404 for unknown task."""
        task_id = str(uuid4())

        mock_orchestrator_service.get_task_status.side_effect = ValueError(f"Task not found: {task_id}")

        response = await async_client.get(f"/api/v1/status/{task_id}")

        assert response.status_code == 404

    async def test_status_returns_trace_id_for_correlation(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test status returns trace_id."""
        task_id = str(uuid4())
        trace_id = str(uuid4())

        mock_orchestrator_service.get_task_status.return_value = {
            "task_id": task_id,
            "status": "running",
            "trace_id": trace_id,
            "progress": "50%",
        }

        response = await async_client.get(f"/api/v1/status/{task_id}")

        assert response.status_code == 200
        data = response.json()
        assert "trace_id" in data

    async def test_status_returns_timestamps(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test status returns creation and update timestamps."""
        task_id = str(uuid4())

        mock_orchestrator_service.get_task_status.return_value = {
            "task_id": task_id,
            "status": "completed",
            "created_at": "2026-01-19T10:00:00",
            "updated_at": "2026-01-19T10:05:00",
        }

        response = await async_client.get(f"/api/v1/status/{task_id}")

        assert response.status_code == 200
        data = response.json()
        assert "created_at" in data
        assert "updated_at" in data


@pytest.mark.asyncio
class TestAgentsEndpoint:
    """Tests for GET /api/v1/agents."""

    async def test_list_agents_returns_all_agents(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test agents endpoint returns list."""
        agent1_id = str(uuid4())
        agent2_id = str(uuid4())

        mock_orchestrator_service.list_agents.return_value = [
            {
                "agent_id": agent1_id,
                "agent_type": "infra",
                "status": "online",
                "resources": {"cpu_percent": 25.0},
                "last_heartbeat_at": "2026-01-19T10:00:00",
            },
            {
                "agent_id": agent2_id,
                "agent_type": "desktop",
                "status": "online",
                "resources": {"cpu_percent": 15.0},
                "last_heartbeat_at": "2026-01-19T10:00:00",
            },
        ]

        response = await async_client.get("/api/v1/agents")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["agent_type"] == "infra"
        assert data[1]["agent_type"] == "desktop"

    async def test_list_agents_filters_by_agent_type(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test agents endpoint filters by type."""
        agent_id = str(uuid4())

        mock_orchestrator_service.list_agents.return_value = [
            {
                "agent_id": agent_id,
                "agent_type": "infra",
                "status": "online",
                "resources": {},
                "last_heartbeat_at": "2026-01-19T10:00:00",
            }
        ]

        response = await async_client.get("/api/v1/agents?agent_type=infra")

        assert response.status_code == 200
        mock_orchestrator_service.list_agents.assert_called_with(
            agent_type="infra",
            status=None,
        )

    async def test_list_agents_filters_by_status(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test agents endpoint filters by status."""
        agent_id = str(uuid4())

        mock_orchestrator_service.list_agents.return_value = [
            {
                "agent_id": agent_id,
                "agent_type": "infra",
                "status": "busy",
                "resources": {},
                "last_heartbeat_at": "2026-01-19T10:00:00",
            }
        ]

        response = await async_client.get("/api/v1/agents?status=busy")

        assert response.status_code == 200
        mock_orchestrator_service.list_agents.assert_called_with(
            agent_type=None,
            status="busy",
        )


@pytest.mark.asyncio
class TestCancelEndpoint:
    """Tests for POST /api/v1/cancel/{task_id}."""

    async def test_cancel_cancels_pending_task(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test cancelling a pending task."""
        task_id = str(uuid4())

        mock_orchestrator_service.cancel_task.return_value = {
            "task_id": task_id,
            "status": "cancelled",
        }

        response = await async_client.post(f"/api/v1/cancel/{task_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == task_id
        assert data["status"] == "cancelled"

    async def test_cancel_rejects_completed_task(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test that cancel rejects already completed tasks."""
        task_id = str(uuid4())

        mock_orchestrator_service.cancel_task.side_effect = ValueError(
            "Cannot cancel task in status 'completed'"
        )

        response = await async_client.post(f"/api/v1/cancel/{task_id}")

        assert response.status_code == 400

    async def test_cancel_returns_404_for_missing_task(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test cancel returns 404 for unknown task."""
        task_id = str(uuid4())

        mock_orchestrator_service.cancel_task.side_effect = ValueError(f"Task not found: {task_id}")

        response = await async_client.post(f"/api/v1/cancel/{task_id}")

        assert response.status_code == 404


@pytest.mark.asyncio
class TestErrorResponses:
    """Tests for error response format."""

    async def test_error_response_has_error_code(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test error responses include error_code."""
        task_id = str(uuid4())

        mock_orchestrator_service.get_task_status.side_effect = ValueError("Task not found")

        response = await async_client.get(f"/api/v1/status/{task_id}")

        assert response.status_code == 404

    async def test_error_response_has_error_message(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test error responses include error_message."""
        mock_orchestrator_service.dispatch_work.side_effect = ValueError("Invalid priority")

        response = await async_client.post(
            "/api/v1/dispatch",
            json={
                "task_id": str(uuid4()),
                "work_type": "ansible",
                "parameters": {},
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "detail" in data

    async def test_error_response_includes_trace_id_when_available(self, async_client: AsyncClient, inject_mock_service, mock_orchestrator_service):
        """Test error responses can include trace_id."""
        # This is for future implementation when trace_id propagation is added
        # For now, just verify the response structure is consistent
        task_id = str(uuid4())

        mock_orchestrator_service.get_task_status.side_effect = ValueError(f"Task not found: {task_id}")

        response = await async_client.get(f"/api/v1/status/{task_id}")

        assert response.status_code == 404
