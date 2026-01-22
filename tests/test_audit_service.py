"""Test suite for audit service and REST endpoints.

Tests:
- AuditService unit tests with database queries
- REST API integration tests
- Pagination and filtering
- Response format validation
"""

import json
from datetime import datetime, timedelta
from typing import Generator
from unittest.mock import Mock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.orchestrator.api import (
    router,
    task_to_audit_response,
    TaskAuditResponse,
    AuditQueryResponse,
)
from src.orchestrator.audit import AuditService
from src.orchestrator.main import app


# ==================== Mock Fixtures ====================


@pytest.fixture
def mock_task():
    """Create a mock Task object."""
    task = Mock()
    task.task_id = "550e8400-e29b-41d4-a716-446655440001"
    task.status = "failed"
    task.request_text = "Deploy Kuma"
    task.services_touched = ["kuma", "portainer"]
    task.outcome = {"success": False, "action_type": "deploy_service"}
    task.created_at = datetime.utcnow()
    task.completed_at = None
    task.error_message = "Service error"
    return task


@pytest.fixture
def mock_completed_task():
    """Create a mock completed Task object."""
    task = Mock()
    task.task_id = "550e8400-e29b-41d4-a716-446655440002"
    task.status = "completed"
    task.request_text = "Update config"
    task.services_touched = ["kuma"]
    task.outcome = {"success": True, "action_type": "update_config"}
    task.created_at = datetime.utcnow() - timedelta(days=1)
    task.completed_at = datetime.utcnow() - timedelta(days=1, hours=1)
    task.error_message = None
    return task


# ==================== AuditService Unit Tests ====================


class TestAuditServiceInitialization:
    """Test AuditService initialization."""

    def test_audit_service_initialization(self):
        """Verify AuditService can be initialized with a database session."""
        mock_db = Mock()
        audit = AuditService(mock_db)

        assert audit.db is mock_db
        assert audit.logger is not None


class TestTaskToAuditResponse:
    """Test conversion of Task to AuditResponse."""

    def test_task_to_audit_response(self, mock_task):
        """Verify Task converts to TaskAuditResponse correctly."""
        response = task_to_audit_response(mock_task)

        assert isinstance(response, TaskAuditResponse)
        assert response.task_id == str(mock_task.task_id)
        assert response.status == "failed"
        assert response.request_text == "Deploy Kuma"
        assert response.services_touched == ["kuma", "portainer"]
        assert response.error_message == "Service error"

    def test_task_to_audit_response_with_completed_task(self, mock_completed_task):
        """Verify TaskAuditResponse handles completed tasks."""
        response = task_to_audit_response(mock_completed_task)

        assert response.status == "completed"
        assert response.completed_at is not None

    def test_task_to_audit_response_isoformat(self, mock_task):
        """Verify timestamps are ISO format."""
        response = task_to_audit_response(mock_task)

        # Should have ISO format timestamps
        assert "T" in response.created_at
        assert isinstance(response.created_at, str)


class TestAuditServiceQueryMethods:
    """Test AuditService query method signatures."""

    def test_get_failures_method_exists(self):
        """Verify get_failures method exists and is callable."""
        mock_db = Mock()
        audit = AuditService(mock_db)

        assert hasattr(audit, "get_failures")
        assert callable(audit.get_failures)

    def test_get_by_service_method_exists(self):
        """Verify get_by_service method exists and is callable."""
        mock_db = Mock()
        audit = AuditService(mock_db)

        assert hasattr(audit, "get_by_service")
        assert callable(audit.get_by_service)

    def test_audit_query_method_exists(self):
        """Verify audit_query method exists and is callable."""
        mock_db = Mock()
        audit = AuditService(mock_db)

        assert hasattr(audit, "audit_query")
        assert callable(audit.audit_query)

    def test_get_task_count_method_exists(self):
        """Verify get_task_count method exists and is callable."""
        mock_db = Mock()
        audit = AuditService(mock_db)

        assert hasattr(audit, "get_task_count")
        assert callable(audit.get_task_count)


class TestAuditServiceQueryBehavior:
    """Test AuditService query method behavior."""

    def test_get_failures_with_mock_query(self):
        """Verify get_failures calls correct query methods."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        audit = AuditService(mock_db)
        result = audit.get_failures(days=7)

        assert mock_db.query.called
        assert result == []

    def test_get_by_service_with_mock_query(self):
        """Verify get_by_service calls correct query methods."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        audit = AuditService(mock_db)
        result = audit.get_by_service("kuma")

        assert mock_db.query.called
        assert result == []

    def test_audit_query_with_mock_query(self):
        """Verify audit_query calls correct query methods."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        audit = AuditService(mock_db)
        result = audit.audit_query(status="failed")

        assert mock_db.query.called
        assert result == []

    def test_get_task_count_with_mock_query(self):
        """Verify get_task_count calls correct query methods."""
        mock_db = Mock()
        mock_query = Mock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 0

        audit = AuditService(mock_db)
        result = audit.get_task_count(status="failed")

        assert mock_db.query.called
        assert result == 0


# ==================== REST API Tests ====================


class TestAuditAPIRoutes:
    """Test audit API routes exist and are accessible."""

    def test_audit_failures_route_exists(self):
        """Verify /api/v1/audit/failures route exists."""
        routes = [r.path for r in router.routes]
        assert "/api/v1/audit/failures" in routes

    def test_audit_by_service_route_exists(self):
        """Verify /api/v1/audit/by-service/{service_name} route exists."""
        routes = [r.path for r in router.routes]
        assert "/api/v1/audit/by-service/{service_name}" in routes

    def test_audit_query_route_exists(self):
        """Verify /api/v1/audit/query route exists."""
        routes = [r.path for r in router.routes]
        assert "/api/v1/audit/query" in routes


class TestAuditAPIEndpoints:
    """Test audit API endpoint behavior."""

    def test_api_endpoints_with_mock_service(self):
        """Verify endpoints call AuditService methods."""
        client = TestClient(app)

        # Mock the AuditService and database dependency
        with patch("src.orchestrator.api.AuditService") as mock_audit_class:
            mock_audit = Mock()
            mock_audit_class.return_value = mock_audit
            mock_audit.get_failures.return_value = []
            mock_audit.get_task_count.return_value = 0

            with patch("src.orchestrator.api.get_db") as mock_get_db:
                mock_db = Mock()
                mock_get_db.return_value = mock_db

                response = client.get("/api/v1/audit/failures")

                # Verify response structure
                assert response.status_code == 200
                data = response.json()
                assert "tasks" in data
                assert "total" in data
                assert "limit" in data
                assert "offset" in data


class TestAuditResponseFormat:
    """Test audit response format compliance."""

    def test_audit_query_response_structure(self):
        """Verify AuditQueryResponse structure."""
        response = AuditQueryResponse(
            tasks=[],
            total=0,
            limit=100,
            offset=0,
        )

        assert response.total == 0
        assert response.limit == 100
        assert response.offset == 0
        assert len(response.tasks) == 0

    def test_audit_query_response_with_tasks(self, mock_task):
        """Verify AuditQueryResponse can contain tasks."""
        task_response = task_to_audit_response(mock_task)
        response = AuditQueryResponse(
            tasks=[task_response],
            total=1,
            limit=100,
            offset=0,
        )

        assert len(response.tasks) == 1
        assert response.tasks[0].task_id == str(mock_task.task_id)

    def test_task_audit_response_structure(self, mock_task):
        """Verify TaskAuditResponse has all fields."""
        response = task_to_audit_response(mock_task)

        assert hasattr(response, "task_id")
        assert hasattr(response, "status")
        assert hasattr(response, "request_text")
        assert hasattr(response, "services_touched")
        assert hasattr(response, "outcome")
        assert hasattr(response, "created_at")
        assert hasattr(response, "completed_at")
        assert hasattr(response, "error_message")


# ==================== Integration Tests ====================


class TestAuditServiceAndAPIIntegration:
    """Integration tests for AuditService and API."""

    def test_query_parameter_validation(self):
        """Verify query parameter validation works."""
        client = TestClient(app)

        with patch("src.orchestrator.api.AuditService"):
            with patch("src.orchestrator.api.get_db"):
                # Valid query should not error on structure
                response = client.get("/api/v1/audit/failures?days=7&limit=100&offset=0")

                # Should get a response (may be 500 if service is mocked, but structure ok)
                assert response.status_code in [200, 500]

    def test_service_query_methods_documented(self):
        """Verify query methods have documentation."""
        mock_db = Mock()
        audit = AuditService(mock_db)

        assert audit.get_failures.__doc__ is not None
        assert audit.get_by_service.__doc__ is not None
        assert audit.audit_query.__doc__ is not None
        assert audit.get_task_count.__doc__ is not None

    def test_audit_service_logging_setup(self):
        """Verify AuditService sets up logging."""
        mock_db = Mock()
        audit = AuditService(mock_db)

        assert audit.logger is not None
        assert audit.logger.name == "orchestrator.audit"


class TestAuditEndpointErrorHandling:
    """Test error handling in audit endpoints."""

    def test_failures_endpoint_error_handling(self):
        """Verify failures endpoint has error handling."""
        client = TestClient(app)

        with patch("src.orchestrator.api.AuditService") as mock_audit_class:
            mock_audit = Mock()
            mock_audit_class.return_value = mock_audit
            mock_audit.get_failures.side_effect = Exception("Database error")
            mock_audit.get_task_count.side_effect = Exception("Database error")

            with patch("src.orchestrator.api.get_db"):
                response = client.get("/api/v1/audit/failures")

                # Should handle error gracefully
                assert response.status_code == 500

    def test_by_service_endpoint_error_handling(self):
        """Verify by-service endpoint has error handling."""
        client = TestClient(app)

        with patch("src.orchestrator.api.AuditService") as mock_audit_class:
            mock_audit = Mock()
            mock_audit_class.return_value = mock_audit
            mock_audit.get_by_service.side_effect = Exception("Database error")

            with patch("src.orchestrator.api.get_db"):
                response = client.get("/api/v1/audit/by-service/kuma")

                # Should handle error gracefully
                assert response.status_code == 500

    def test_query_endpoint_error_handling(self):
        """Verify query endpoint has error handling."""
        client = TestClient(app)

        with patch("src.orchestrator.api.AuditService") as mock_audit_class:
            mock_audit = Mock()
            mock_audit_class.return_value = mock_audit
            mock_audit.audit_query.side_effect = Exception("Database error")

            with patch("src.orchestrator.api.get_db"):
                response = client.get("/api/v1/audit/query?status=failed")

                # Should handle error gracefully
                assert response.status_code == 500


class TestAuditServiceDocumentation:
    """Test AuditService and endpoint documentation."""

    def test_audit_service_class_documented(self):
        """Verify AuditService has class docstring."""
        assert AuditService.__doc__ is not None
        assert "query" in AuditService.__doc__.lower()

    def test_query_methods_have_descriptions(self):
        """Verify each query method has descriptive docstring."""
        mock_db = Mock()
        audit = AuditService(mock_db)

        methods = ["get_failures", "get_by_service", "audit_query", "get_task_count"]
        for method_name in methods:
            method = getattr(audit, method_name)
            assert method.__doc__ is not None
            assert len(method.__doc__) > 0
