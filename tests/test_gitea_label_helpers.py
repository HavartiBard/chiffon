"""Tests for Gitea label helper functions in cli."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.chiffon.cli import get_or_create_label, add_issue_label


@pytest.mark.asyncio
async def test_get_or_create_label_returns_existing_id():
    """Returns the label ID when label already exists."""
    mock_client = AsyncMock()
    mock_list_resp = MagicMock()
    mock_list_resp.status_code = 200
    mock_list_resp.json.return_value = [
        {"id": 42, "name": "chiffon:blocked", "color": "#e11d48"},
        {"id": 7,  "name": "bug",             "color": "#d73a4a"},
    ]
    mock_client.get.return_value = mock_list_resp

    label_id = await get_or_create_label(
        mock_client, "https://code.klsll.com", "HavartiBard", "chiffon",
        "test-token", "chiffon:blocked"
    )

    assert label_id == 42
    mock_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_label_creates_when_missing():
    """Creates the label and returns new ID when label does not exist."""
    mock_client = AsyncMock()

    mock_list_resp = MagicMock()
    mock_list_resp.status_code = 200
    mock_list_resp.json.return_value = []
    mock_client.get.return_value = mock_list_resp

    mock_create_resp = MagicMock()
    mock_create_resp.status_code = 201
    mock_create_resp.json.return_value = {"id": 99, "name": "chiffon:blocked"}
    mock_client.post.return_value = mock_create_resp

    label_id = await get_or_create_label(
        mock_client, "https://code.klsll.com", "HavartiBard", "chiffon",
        "test-token", "chiffon:blocked", color="#e11d48"
    )

    assert label_id == 99
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert call_kwargs[1]["json"]["name"] == "chiffon:blocked"
    assert call_kwargs[1]["json"]["color"] == "#e11d48"


@pytest.mark.asyncio
async def test_add_issue_label_calls_gitea_api():
    """add_issue_label looks up or creates label then POSTs to issue labels endpoint."""
    mock_client = AsyncMock()

    mock_list_resp = MagicMock()
    mock_list_resp.status_code = 200
    mock_list_resp.json.return_value = [{"id": 5, "name": "chiffon:blocked"}]
    mock_client.get.return_value = mock_list_resp

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_client.post.return_value = mock_post_resp

    await add_issue_label(
        mock_client, "https://code.klsll.com", "HavartiBard", "chiffon",
        "test-token", issue_number=12, label_name="chiffon:blocked"
    )

    label_post_call = mock_client.post.call_args
    assert "/issues/12/labels" in label_post_call[0][0]
    assert label_post_call[1]["json"]["labels"] == [5]
