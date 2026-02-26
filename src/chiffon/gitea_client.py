"""Gitea API client for fetching issues and transforming them into tasks."""

from typing import Any


class GiteaClient:
    """Client for interacting with Gitea API."""

    def __init__(
        self,
        base_url: str,
        project_owner: str,
        project_name: str,
        token: str,
        http_client: Any = None,
    ):
        """Initialize Gitea client.

        Args:
            base_url: Gitea server base URL
            project_owner: Repository owner
            project_name: Repository name
            token: API token for authentication
            http_client: Optional HTTP client (for testing)
        """
        self.base_url = base_url
        self.project_owner = project_owner
        self.project_name = project_name
        self.token = token
        self.http_client = http_client

    async def fetch_open_issues(self, label: str | None = None) -> list[dict[str, Any]]:
        """Fetch all open issues from the project.

        Args:
            label: Optional label to filter issues by

        Returns:
            List of issue dictionaries
        """
        url = f"{self.base_url}/api/v1/repos/{self.project_owner}/{self.project_name}/issues"
        params = {"state": "open"}
        if label:
            params["labels"] = label

        response = await self.http_client.get(
            url,
            headers={"Authorization": f"token {self.token}"},
            params=params,
        )
        result = response.json()
        if hasattr(result, "__await__"):
            return await result
        return result
