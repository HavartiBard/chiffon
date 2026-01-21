"""Infrastructure Agent for Ansible playbook execution and orchestration.

Provides:
- InfraAgent class that extends BaseAgent
- Service-level task mapping to Ansible playbooks
- Playbook discovery and cataloging
- Placeholder execution (Plan 03 will implement)
"""

import logging
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from src.agents.base import BaseAgent
from src.common.config import Config
from src.common.protocol import WorkRequest, WorkResult

logger = logging.getLogger(__name__)


class InfraAgent(BaseAgent):
    """Infrastructure agent for Ansible playbook execution.

    Extends BaseAgent with:
    - Playbook discovery from ~/CascadeProjects/homelab-infra/ansible
    - Service-level intent mapping to playbooks
    - Ansible execution with structured output (Plan 03)
    - Post-failure analysis and suggestions (Plan 04)
    """

    def __init__(
        self,
        agent_id: str,
        config: Config,
        repo_path: str = "~/CascadeProjects/homelab-infra/ansible",
    ):
        """Initialize the infrastructure agent.

        Args:
            agent_id: Unique identifier for this agent
            config: Configuration object with RabbitMQ and DB settings
            repo_path: Path to Ansible playbook repository (defaults to homelab-infra)
        """
        super().__init__(agent_id, "infra", config)

        # Import PlaybookDiscovery here to avoid circular dependency
        from .playbook_discovery import PlaybookDiscovery

        self.repo_path = Path(repo_path).expanduser()
        self.playbook_discovery = PlaybookDiscovery(str(self.repo_path))

        self.logger.info(
            f"InfraAgent initialized: agent_id={agent_id}, repo_path={self.repo_path}"
        )

    def get_agent_capabilities(self) -> dict[str, Any]:
        """Report agent capabilities to orchestrator.

        Returns:
            Dict mapping capability to boolean (True if supported)
        """
        return {
            "run_playbook": True,
            "discover_playbooks": True,
            "generate_template": True,
            "analyze_playbook": True,
        }

    async def execute_work(self, work_request: WorkRequest) -> WorkResult:
        """Execute infrastructure work request (stub for Plan 01).

        Plan 01 focuses on agent foundation and playbook discovery.
        Actual playbook execution will be implemented in Plan 03.

        Args:
            work_request: The work request with task_id, work_type, and parameters

        Returns:
            WorkResult with status="completed" and placeholder message
        """
        self.logger.info(
            f"InfraAgent received work request: work_type={work_request.work_type}",
            extra={
                "task_id": str(work_request.task_id),
                "work_type": work_request.work_type,
                "parameters": work_request.parameters,
            },
        )

        # Plan 01 stub: Just log and return placeholder
        output = (
            "InfraAgent stub - execution in Plan 03\n"
            f"Work type: {work_request.work_type}\n"
            f"Parameters: {work_request.parameters}"
        )

        return WorkResult(
            task_id=work_request.task_id,
            status="completed",
            exit_code=0,
            output=output,
            duration_ms=0,
            resources_used={},
        )

    async def discover_playbooks(self, force_refresh: bool = False) -> list[dict]:
        """Discover playbooks from repository.

        Delegates to PlaybookDiscovery service for scanning, parsing, and caching.

        Args:
            force_refresh: If True, ignore cache and rescan repository

        Returns:
            List of playbook metadata dictionaries
        """
        self.logger.info(
            f"Discovering playbooks: force_refresh={force_refresh}, repo={self.repo_path}"
        )

        playbooks = await self.playbook_discovery.discover_playbooks(force_refresh)

        self.logger.info(f"Discovered {len(playbooks)} playbooks")
        return [pb.model_dump() for pb in playbooks]

    async def get_playbook_catalog(self) -> list[dict]:
        """Get cached playbook catalog without rescanning.

        Returns:
            List of cached playbook metadata dictionaries (empty if cache invalid)
        """
        catalog = self.playbook_discovery.get_cached_catalog()
        self.logger.debug(f"Returning cached catalog with {len(catalog)} playbooks")
        return [pb.model_dump() for pb in catalog]
