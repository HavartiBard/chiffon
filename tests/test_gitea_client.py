"""Test-driven development for Gitea client integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.chiffon.gitea_client import GiteaClient


@pytest.mark.asyncio
async def test_gitea_client_fetches_open_issues():
    """Test that GiteaClient fetches open issues from a Gitea project."""
    # Mock HTTP client
    mock_http = AsyncMock()
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {
            "id": 1,
            "title": "Deploy Kuma to production",
            "body": "Please deploy Kuma service with scaling enabled",
            "state": "open",
            "created_at": "2026-02-02T10:00:00Z",
            "labels": [{"name": "automation"}, {"name": "infra"}],
        },
        {
            "id": 2,
            "title": "Update portal configuration",
            "body": "Sync configuration for all portals",
            "state": "open",
            "created_at": "2026-02-02T11:00:00Z",
            "labels": [{"name": "automation"}],
        },
    ]
    mock_response.status_code = 200
    mock_http.get.return_value = mock_response

    # Create client and fetch issues
    client = GiteaClient(
        base_url="http://gitea.local",
        project_owner="chiffon",
        project_name="tasks",
        token="test-token",
        http_client=mock_http,
    )

    issues = await client.fetch_open_issues()

    # Verify
    assert len(issues) == 2
    assert issues[0]["title"] == "Deploy Kuma to production"
    assert issues[1]["title"] == "Update portal configuration"
    assert issues[0]["state"] == "open"
    mock_http.get.assert_called_once()


@pytest.mark.asyncio
async def test_gitea_client_filters_by_label():
    """Test that GiteaClient can filter issues by label."""
    mock_http = AsyncMock()
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {
            "id": 1,
            "title": "Deploy Kuma to production",
            "labels": [{"name": "automation"}],
        }
    ]
    mock_http.get.return_value = mock_response

    client = GiteaClient(
        base_url="http://gitea.local",
        project_owner="chiffon",
        project_name="tasks",
        token="test-token",
        http_client=mock_http,
    )

    issues = await client.fetch_open_issues(label="automation")

    assert len(issues) == 1
    # Verify the label filter was passed in the request
    call_args = mock_http.get.call_args
    assert call_args[1]["params"]["labels"] == "automation"
