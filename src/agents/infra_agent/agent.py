"""Infrastructure Agent for Ansible playbook execution and orchestration.

Provides:
- InfraAgent class that extends BaseAgent
- Service-level task mapping to Ansible playbooks
- Playbook discovery and cataloging
- Template generation for new playbooks
- Placeholder execution (Plan 03 will implement)
"""

import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from src.agents.base import BaseAgent
from src.common.config import Config
from src.common.protocol import WorkRequest, WorkResult

from .analyzer import PlaybookAnalyzer
from .executor import (
    AnsibleRunnerError,
    ExecutionSummary,
    ExecutionTimeoutError,
    PlaybookExecutor,
    PlaybookNotFoundError,
)
from .template_generator import TemplateGenerator

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
        self.template_generator = TemplateGenerator()
        self.executor = PlaybookExecutor(str(self.repo_path))
        # Get database session from config if available
        db_session = getattr(config, "db_session", None)
        self.analyzer = PlaybookAnalyzer(db_session=db_session)

        self.logger.info(f"InfraAgent initialized: agent_id={agent_id}, repo_path={self.repo_path}")

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
        """Execute infrastructure work request.

        Supports work types:
        - generate_template: Generate Ansible playbook scaffold
        - deploy_service: Deploy service via Ansible (Plan 03)
        - discover_playbooks: Scan repository for playbooks

        Args:
            work_request: The work request with task_id, work_type, and parameters

        Returns:
            WorkResult with status and output
        """
        self.logger.info(
            f"InfraAgent received work request: work_type={work_request.work_type}",
            extra={
                "task_id": str(work_request.task_id),
                "work_type": work_request.work_type,
                "parameters": work_request.parameters,
            },
        )

        # Handle generate_template work type
        if work_request.work_type == "generate_template":
            return await self._handle_generate_template(work_request)

        # Handle analyze_playbook work type
        if work_request.work_type == "analyze_playbook":
            return await self._handle_analyze_playbook(work_request)

        # Handle run_playbook work type
        if work_request.work_type == "run_playbook":
            return await self._handle_run_playbook(work_request)

        # Handle deploy_service work type
        if work_request.work_type == "deploy_service":
            return await self._handle_deploy_service(work_request)

        # Handle discover_playbooks work type
        if work_request.work_type == "discover_playbooks":
            return await self._handle_discover_playbooks(work_request)

        # Unknown work type
        self.logger.error(
            f"Unknown work type: {work_request.work_type}",
            extra={"task_id": str(work_request.task_id)},
        )
        from uuid import uuid4

        return WorkResult(
            task_id=work_request.task_id,
            status="failed",
            exit_code=1,
            output="",
            error_message=f"Unknown work type: {work_request.work_type}",
            duration_ms=0,
            agent_id=uuid4(),
            resources_used={},
        )

    async def _handle_generate_template(self, work_request: WorkRequest) -> WorkResult:
        """Handle generate_template work type.

        Parameters:
            service_name: Service name (required)
            description: Service description (optional)
            service_port: Service port (optional, default 8080)
            hosts: Ansible hosts pattern (optional, default "all")
            become: Use privilege escalation (optional, default True)
            extra_vars: Additional template variables (optional)
            write_to_disk: If True, write template to output_dir (optional, default False)
            output_dir: Directory to write template (optional, default "./generated")

        Returns:
            WorkResult with generated template content
        """
        import time
        from uuid import uuid4

        start_time = time.time()

        try:
            # Extract parameters
            service_name = work_request.parameters.get("service_name")
            if not service_name:
                error_msg = "service_name parameter is required"
                return WorkResult(
                    task_id=work_request.task_id,
                    status="failed",
                    exit_code=1,
                    output=f"Error: {error_msg}",
                    error_message=error_msg,
                    duration_ms=0,
                    agent_id=uuid4(),
                    resources_used={},
                )

            description = work_request.parameters.get("description")
            service_port = work_request.parameters.get("service_port", 8080)
            hosts = work_request.parameters.get("hosts", "all")
            become = work_request.parameters.get("become", True)
            extra_vars = work_request.parameters.get("extra_vars")
            write_to_disk = work_request.parameters.get("write_to_disk", False)
            output_dir = work_request.parameters.get("output_dir", "./generated")

            # Generate template
            template = await self.template_generator.generate_template(
                service_name=service_name,
                description=description,
                service_port=service_port,
                hosts=hosts,
                become=become,
                extra_vars=extra_vars,
            )

            # Optionally write to disk
            written_paths = []
            if write_to_disk:
                paths = await self.template_generator.write_template_to_disk(
                    template=template,
                    output_dir=Path(output_dir),
                    overwrite=False,
                )
                written_paths = [str(p) for p in paths]

            # Build output
            output_data = {
                "service_name": template.service_name,
                "playbook_content": template.playbook_content,
                "role_structure": template.role_structure,
                "readme_content": template.readme_content,
                "output_paths": template.output_paths,
                "written_paths": written_paths if write_to_disk else [],
            }

            duration_ms = int((time.time() - start_time) * 1000)

            return WorkResult(
                task_id=work_request.task_id,
                status="completed",
                exit_code=0,
                output=json.dumps(output_data, indent=2),
                duration_ms=duration_ms,
                agent_id=uuid4(),
                resources_used={},
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self.logger.error(f"Template generation failed: {e}", exc_info=True)

            error_msg = str(e)
            return WorkResult(
                task_id=work_request.task_id,
                status="failed",
                exit_code=1,
                output=f"Template generation failed: {error_msg}",
                error_message=error_msg,
                duration_ms=duration_ms,
                agent_id=uuid4(),
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

    async def _handle_analyze_playbook(self, work_request: WorkRequest) -> WorkResult:
        """Handle analyze_playbook work type.

        Parameters:
            playbook_path: Path to playbook file (required)

        Returns:
            WorkResult with analysis results as JSON
        """
        import time
        from uuid import uuid4

        start_time = time.time()

        try:
            playbook_path = work_request.parameters.get("playbook_path")
            if not playbook_path:
                return WorkResult(
                    task_id=work_request.task_id,
                    status="failed",
                    exit_code=1,
                    output="",
                    error_message="playbook_path parameter is required",
                    duration_ms=0,
                    agent_id=uuid4(),
                    resources_used={},
                )

            # Analyze playbook
            analysis_result = await self.analyzer.analyze_playbook(
                playbook_path=playbook_path,
                task_id=str(work_request.task_id),
            )

            # Convert to JSON
            output_data = {
                "playbook_path": analysis_result.playbook_path,
                "total_issues": analysis_result.total_issues,
                "by_category": analysis_result.by_category,
                "suggestions": [s.model_dump() for s in analysis_result.suggestions],
                "analyzed_at": analysis_result.analyzed_at.isoformat(),
            }

            duration_ms = int((time.time() - start_time) * 1000)

            self.logger.info(
                f"Analysis complete: {analysis_result.total_issues} issues found in {len(analysis_result.by_category)} categories"
            )

            return WorkResult(
                task_id=work_request.task_id,
                status="completed",
                exit_code=0,
                output=json.dumps(output_data, indent=2),
                duration_ms=duration_ms,
                agent_id=uuid4(),
                resources_used={},
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self.logger.error(f"Playbook analysis failed: {e}", exc_info=True)

            return WorkResult(
                task_id=work_request.task_id,
                status="failed",
                exit_code=1,
                output="",
                error_message=f"Playbook analysis failed: {str(e)}",
                duration_ms=duration_ms,
                agent_id=uuid4(),
                resources_used={},
            )

    async def _handle_run_playbook(self, work_request: WorkRequest) -> WorkResult:
        """Handle run_playbook work type using PlaybookExecutor.

        Parameters:
            playbook_path: Path to playbook file (required)
            extravars: Extra variables to pass to playbook (optional)
            inventory: Inventory file to use (optional)
            limit: Limit execution to specific hosts (optional)
            tags: Only run tasks with these tags (optional)
            timeout_seconds: Maximum execution time (optional, default 600)

        Returns:
            WorkResult with execution summary
        """
        playbook_path = work_request.parameters.get("playbook_path")
        extravars = work_request.parameters.get("extravars")
        inventory = work_request.parameters.get("inventory")
        limit = work_request.parameters.get("limit")
        tags = work_request.parameters.get("tags")
        timeout_seconds = work_request.parameters.get("timeout_seconds", 600)

        if not playbook_path:
            from uuid import uuid4

            return WorkResult(
                task_id=work_request.task_id,
                status="failed",
                exit_code=1,
                output="",
                error_message="Missing required parameter: playbook_path",
                duration_ms=0,
                agent_id=uuid4(),
                resources_used={},
            )

        try:
            summary = await self.executor.execute_playbook(
                playbook_path=playbook_path,
                extravars=extravars,
                inventory=inventory,
                limit=limit,
                tags=tags,
                timeout_seconds=timeout_seconds,
            )

            # Resolve playbook path for analysis (relative to repo_path)
            resolved_playbook = (self.repo_path / playbook_path).resolve()

            return await self._summary_to_result(
                work_request.task_id, summary, str(resolved_playbook)
            )

        except PlaybookNotFoundError as e:
            from uuid import uuid4

            return WorkResult(
                task_id=work_request.task_id,
                status="failed",
                exit_code=2,
                output="",
                error_message=f"Playbook not found: {str(e)}",
                duration_ms=0,
                agent_id=uuid4(),
                resources_used={},
            )

        except ExecutionTimeoutError as e:
            from uuid import uuid4

            return WorkResult(
                task_id=work_request.task_id,
                status="failed",
                exit_code=124,  # Standard timeout exit code
                output="",
                error_message=f"Execution timeout: {str(e)}",
                duration_ms=timeout_seconds * 1000,
                agent_id=uuid4(),
                resources_used={},
            )

        except AnsibleRunnerError as e:
            from uuid import uuid4

            return WorkResult(
                task_id=work_request.task_id,
                status="failed",
                exit_code=1,
                output="",
                error_message=f"Ansible runner error: {str(e)}",
                duration_ms=0,
                agent_id=uuid4(),
                resources_used={},
            )

    async def _handle_deploy_service(self, work_request: WorkRequest) -> WorkResult:
        """Handle deploy_service work type with task mapping and execution.

        Parameters:
            task_intent: Natural language task description (required)
            extravars: Extra variables to pass to playbook (optional)
            inventory: Inventory file to use (optional)
            limit: Limit execution to specific hosts (optional)
            tags: Only run tasks with these tags (optional)
            timeout_seconds: Maximum execution time (optional, default 600)

        Returns:
            WorkResult with execution summary
        """
        task_intent = work_request.parameters.get("task_intent")

        if not task_intent:
            from uuid import uuid4

            return WorkResult(
                task_id=work_request.task_id,
                status="failed",
                exit_code=1,
                output="",
                error_message="Missing required parameter: task_intent",
                duration_ms=0,
                agent_id=uuid4(),
                resources_used={},
            )

        # Import TaskMapper and CacheManager here to avoid circular deps
        # Create cache manager and task mapper
        # Note: In production, these should be initialized once in __init__
        # For now, create them per-request for simplicity
        from src.common.config import Config

        from .cache_manager import CacheManager
        from .task_mapper import TaskMapper

        cache_manager = CacheManager(Config())

        # Get playbook catalog
        catalog_dicts = await self.discover_playbooks(force_refresh=False)

        # Convert to PlaybookMetadata objects for TaskMapper
        from .task_mapper import PlaybookMetadata

        catalog = [PlaybookMetadata(**pb) for pb in catalog_dicts]

        # Map task to playbook
        task_mapper = TaskMapper(cache_manager, catalog)
        mapping_result = await task_mapper.map_task_to_playbook(task_intent)

        if not mapping_result.playbook_path:
            from uuid import uuid4

            suggestion = mapping_result.suggestion or "No suggestion available"
            return WorkResult(
                task_id=work_request.task_id,
                status="failed",
                exit_code=1,
                output=f"No matching playbook found.\n{suggestion}",
                error_message=f"No playbook matched task intent: {task_intent}",
                duration_ms=0,
                agent_id=uuid4(),
                resources_used={},
            )

        # Execute the mapped playbook
        extravars = work_request.parameters.get("extravars")
        inventory = work_request.parameters.get("inventory")
        limit = work_request.parameters.get("limit")
        tags = work_request.parameters.get("tags")
        timeout_seconds = work_request.parameters.get("timeout_seconds", 600)

        try:
            summary = await self.executor.execute_playbook(
                playbook_path=mapping_result.playbook_path,
                extravars=extravars,
                inventory=inventory,
                limit=limit,
                tags=tags,
                timeout_seconds=timeout_seconds,
            )

            return await self._summary_to_result(
                work_request.task_id, summary, mapping_result.playbook_path
            )

        except (PlaybookNotFoundError, ExecutionTimeoutError, AnsibleRunnerError) as e:
            from uuid import uuid4

            return WorkResult(
                task_id=work_request.task_id,
                status="failed",
                exit_code=1,
                output="",
                error_message=str(e),
                duration_ms=0,
                agent_id=uuid4(),
                resources_used={},
            )

    async def _handle_discover_playbooks(self, work_request: WorkRequest) -> WorkResult:
        """Handle discover_playbooks work type.

        Parameters:
            force_refresh: If True, ignore cache and rescan repository (optional, default False)

        Returns:
            WorkResult with playbook catalog in output
        """
        force_refresh = work_request.parameters.get("force_refresh", False)

        try:
            catalog = await self.discover_playbooks(force_refresh=force_refresh)
            from uuid import uuid4

            # Convert catalog to JSON, handling datetime serialization
            # Use default=str to convert datetime objects to ISO format strings
            output = json.dumps(catalog, indent=2, default=str)

            return WorkResult(
                task_id=work_request.task_id,
                status="completed",
                exit_code=0,
                output=output,
                duration_ms=0,
                agent_id=uuid4(),
                resources_used={},
            )

        except Exception as e:
            from uuid import uuid4

            return WorkResult(
                task_id=work_request.task_id,
                status="failed",
                exit_code=1,
                output="",
                error_message=f"Failed to discover playbooks: {str(e)}",
                duration_ms=0,
                agent_id=uuid4(),
                resources_used={},
            )

    async def _summary_to_result(
        self, task_id: UUID, summary: ExecutionSummary, playbook_path: str
    ) -> WorkResult:
        """Convert ExecutionSummary to WorkResult.

        Args:
            task_id: Task ID from work request
            summary: Execution summary from PlaybookExecutor
            playbook_path: Path to the executed playbook (for analysis on failure)

        Returns:
            WorkResult with formatted output and optional analysis
        """
        from uuid import uuid4

        # Format output
        output_lines = [
            f"Status: {summary.status}",
            f"Duration: {summary.duration_ms}ms",
            f"Tasks: {summary.ok_count} ok, {summary.changed_count} changed, "
            f"{summary.failed_count} failed, {summary.skipped_count} skipped",
        ]

        if summary.failed_tasks:
            output_lines.append("\nFailed tasks:")
            for task in summary.failed_tasks:
                output_lines.append(f"  - {task}")

        if summary.key_errors:
            output_lines.append("\nKey errors:")
            for error in summary.key_errors:
                output_lines.append(f"  - {error}")

        if summary.hosts_summary:
            output_lines.append("\nHost summary:")
            for host, stats in summary.hosts_summary.items():
                output_lines.append(
                    f"  {host}: {stats['ok']} ok, {stats['changed']} changed, "
                    f"{stats['failures']} failed"
                )

        # Determine status and error message
        status = "completed" if summary.status == "successful" else "failed"
        error_message = None
        analysis_result = None

        # If failed, run playbook analyzer
        if status == "failed" and playbook_path:
            try:
                analysis = await self.analyzer.analyze_playbook(
                    playbook_path=playbook_path,
                    task_id=str(task_id),
                )
                analysis_result = analysis.model_dump()
                self.logger.info(
                    f"Playbook analysis after failure: {analysis.total_issues} suggestions generated"
                )

                # Add analysis summary to output
                output_lines.append(f"\nAnalysis: {analysis.total_issues} improvement suggestions")
                if analysis.by_category:
                    output_lines.append(
                        f"Categories: {', '.join(f'{k}: {v}' for k, v in analysis.by_category.items())}"
                    )
            except Exception as e:
                self.logger.error(f"Post-failure analysis failed: {e}", exc_info=True)

        if summary.status != "successful":
            error_message = f"Playbook execution {summary.status}"
            if summary.key_errors:
                error_message += f": {summary.key_errors[0]}"

        output = "\n".join(output_lines)

        return WorkResult(
            task_id=task_id,
            status=status,
            exit_code=summary.exit_code,
            output=output,
            error_message=error_message,
            duration_ms=summary.duration_ms,
            agent_id=uuid4(),
            resources_used={},
            analysis_result=analysis_result,
        )
