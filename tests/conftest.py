"""Pytest configuration and shared fixtures."""

import pytest
from httpx import AsyncClient

from src.orchestrator.main import app


@pytest.fixture
async def async_client():
    """Provide an async HTTP client for testing FastAPI routes.

    Yields:
        AsyncClient: HTTP client configured for the FastAPI app.
    """
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture
def test_database_url():
    """Provide a test database URL using in-memory SQLite.

    This is a placeholder for Phase 2 when database integration is added.

    Yields:
        str: SQLite in-memory database URL.
    """
    yield "sqlite:///:memory:"
