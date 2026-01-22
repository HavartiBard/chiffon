"""Playbook executor service for running Ansible playbooks via ansible-runner.

Provides:
- PlaybookExecutor: Service for running Ansible playbooks with structured output
- ExecutionSummary: Pydantic model for playbook execution results
- Custom exceptions for execution failures
"""

import asyncio
import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ExecutionSummary(BaseModel):
    """Structured summary of Ansible playbook execution.

    Provides high-level execution results without streaming line-by-line output.
    This reduces RabbitMQ overhead for large playbook executions.
    """

    status: str = Field(
        description="Execution status: successful, failed, timeout, cancelled"
    )
    exit_code: int = Field(description="Ansible-runner return code (0=success)")
    duration_ms: int = Field(description="Total execution time in milliseconds")
    changed_count: int = Field(default=0, description="Number of tasks that changed state")
    ok_count: int = Field(default=0, description="Number of successful tasks")
    failed_count: int = Field(default=0, description="Number of failed tasks")
    skipped_count: int = Field(default=0, description="Number of skipped tasks")
    failed_tasks: list[str] = Field(
        default_factory=list, description="Names of failed tasks"
    )
    key_errors: list[str] = Field(
        default_factory=list,
        description="Error messages from failed tasks (max 5)",
        max_length=5,
    )
    hosts_summary: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-host statistics: {hostname: {ok, changed, failures}}",
    )


class PlaybookNotFoundError(Exception):
    """Raised when playbook file does not exist."""

    pass


class ExecutionTimeoutError(Exception):
    """Raised when playbook execution exceeds timeout."""

    pass


class AnsibleRunnerError(Exception):
    """Wrapper for ansible-runner internal errors."""

    pass


class PlaybookExecutor:
    """Service for executing Ansible playbooks via ansible-runner.

    Uses ansible-runner library for playbook execution with event-based
    processing to generate structured summaries instead of streaming output.

    Attributes:
        repo_path: Path to Ansible repository root
        artifact_retention: Number of artifact directories to retain
    """

    def __init__(self, repo_path: str, artifact_retention: int = 10):
        """Initialize playbook executor.

        Args:
            repo_path: Path to Ansible repository (must exist)
            artifact_retention: Number of ansible-runner artifacts to keep

        Raises:
            ValueError: If repo_path does not exist
        """
        self.repo_path = Path(repo_path).expanduser().resolve()
        self.artifact_retention = artifact_retention

        if not self.repo_path.exists():
            raise ValueError(f"Repository path does not exist: {self.repo_path}")

        logger.info(
            f"PlaybookExecutor initialized: repo={self.repo_path}, "
            f"artifact_retention={self.artifact_retention}"
        )

    async def execute_playbook(
        self,
        playbook_path: str,
        extravars: Optional[dict[str, Any]] = None,
        inventory: Optional[str] = None,
        limit: Optional[str] = None,
        tags: Optional[list[str]] = None,
        timeout_seconds: int = 600,
    ) -> ExecutionSummary:
        """Execute an Ansible playbook with structured output.

        Args:
            playbook_path: Path to playbook (relative to repo_path or absolute)
            extravars: Extra variables to pass to playbook
            inventory: Inventory file to use (default: "inventory")
            limit: Limit execution to specific hosts
            tags: Only run tasks with these tags
            timeout_seconds: Maximum execution time (default: 600)

        Returns:
            ExecutionSummary with structured execution results

        Raises:
            PlaybookNotFoundError: If playbook file does not exist
            ExecutionTimeoutError: If execution exceeds timeout_seconds
            AnsibleRunnerError: If ansible-runner encounters internal error
        """
        # Validate playbook exists
        resolved_playbook = await self._validate_playbook_exists(playbook_path)

        # Make playbook_path relative to repo_path for ansible-runner
        try:
            relative_playbook = resolved_playbook.relative_to(self.repo_path)
        except ValueError:
            # If playbook is outside repo_path, use absolute path
            relative_playbook = resolved_playbook

        logger.info(
            f"Executing playbook: {relative_playbook}",
            extra={
                "playbook": str(relative_playbook),
                "extravars": extravars,
                "inventory": inventory,
                "timeout": timeout_seconds,
            },
        )

        # Handle complex extravars by writing to temp file
        extravars_file = None
        if extravars and self._is_complex_extravars(extravars):
            extravars_file = await self._write_extravars_file(extravars)
            extravars_arg = f"@{extravars_file}"
        else:
            extravars_arg = extravars or {}

        # Build ansible-runner configuration
        runner_config = {
            "private_data_dir": str(self.repo_path),
            "playbook": str(relative_playbook),
            "inventory": inventory or "inventory",
            "quiet": True,  # Suppress stdout streaming
            "rotate_artifacts": self.artifact_retention,
        }

        # Add optional parameters
        if isinstance(extravars_arg, str):
            # File-based extravars
            runner_config["cmdline"] = f"--extra-vars {extravars_arg}"
        elif extravars_arg:
            runner_config["extravars"] = extravars_arg

        if limit:
            runner_config["limit"] = limit

        if tags:
            runner_config["tags"] = ",".join(tags)

        try:
            # Execute playbook with timeout
            start_time = datetime.utcnow()
            runner = await asyncio.wait_for(
                asyncio.to_thread(self._run_ansible_sync, runner_config),
                timeout=timeout_seconds,
            )
            end_time = datetime.utcnow()

            # Process events into summary
            summary = self._process_events(runner, start_time, end_time)

            logger.info(
                f"Playbook execution complete: status={summary.status}, "
                f"duration={summary.duration_ms}ms, changed={summary.changed_count}",
                extra={
                    "playbook": str(relative_playbook),
                    "status": summary.status,
                    "exit_code": summary.exit_code,
                },
            )

            return summary

        except asyncio.TimeoutError:
            logger.error(
                f"Playbook execution timed out after {timeout_seconds}s",
                extra={"playbook": str(relative_playbook)},
            )
            raise ExecutionTimeoutError(
                f"Playbook execution exceeded {timeout_seconds}s timeout"
            )

        except Exception as e:
            logger.error(
                f"Ansible-runner error: {e}",
                extra={"playbook": str(relative_playbook), "error": str(e)},
                exc_info=True,
            )
            raise AnsibleRunnerError(f"Ansible-runner execution failed: {e}") from e

        finally:
            # Cleanup temp extravars file if created
            if extravars_file and Path(extravars_file).exists():
                Path(extravars_file).unlink()

    def _run_ansible_sync(self, config: dict) -> Any:
        """Synchronous wrapper for ansible_runner.run().

        This method is called via asyncio.to_thread() to avoid blocking
        the event loop during playbook execution.

        Args:
            config: ansible-runner configuration dict

        Returns:
            ansible_runner.Runner object with events and stats
        """
        try:
            import ansible_runner
        except ImportError as e:
            raise AnsibleRunnerError(
                "ansible-runner not installed. Install with: pip install ansible-runner"
            ) from e

        return ansible_runner.run(**config)

    def _process_events(
        self, runner: Any, start_time: datetime, end_time: datetime
    ) -> ExecutionSummary:
        """Process ansible-runner events into ExecutionSummary.

        Extracts task counts, failed tasks, and error messages from
        ansible-runner event stream.

        Args:
            runner: ansible_runner.Runner object
            start_time: Execution start timestamp
            end_time: Execution end timestamp

        Returns:
            ExecutionSummary with structured results
        """
        # Initialize counters
        changed_count = 0
        ok_count = 0
        failed_count = 0
        skipped_count = 0
        failed_tasks: list[str] = []
        key_errors: list[str] = []

        # Process events
        if hasattr(runner, "events") and runner.events:
            for event in runner.events:
                event_data = event.get("event_data", {})
                event_type = event.get("event", "")

                if event_type == "runner_on_ok":
                    ok_count += 1
                    # Check if task changed state
                    if event_data.get("res", {}).get("changed", False):
                        changed_count += 1

                elif event_type == "runner_on_failed":
                    failed_count += 1
                    # Capture task name
                    task_name = event_data.get("task", "Unknown task")
                    failed_tasks.append(task_name)

                    # Capture error message (limit to 5)
                    if len(key_errors) < 5:
                        error_msg = (
                            event_data.get("res", {}).get("msg")
                            or event_data.get("res", {}).get("stderr")
                            or "Unknown error"
                        )
                        key_errors.append(f"{task_name}: {error_msg}")

                elif event_type == "runner_on_skipped":
                    skipped_count += 1

        # Build hosts_summary from runner.stats if available
        hosts_summary = {}
        if hasattr(runner, "stats") and runner.stats:
            for hostname, stats in runner.stats.items():
                hosts_summary[hostname] = {
                    "ok": stats.get("ok", 0),
                    "changed": stats.get("changed", 0),
                    "failures": stats.get("failures", 0),
                    "skipped": stats.get("skipped", 0),
                }

        # Calculate duration
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        # Determine status from runner return code
        status = "successful" if runner.rc == 0 else "failed"

        return ExecutionSummary(
            status=status,
            exit_code=runner.rc,
            duration_ms=duration_ms,
            changed_count=changed_count,
            ok_count=ok_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            failed_tasks=failed_tasks,
            key_errors=key_errors,
            hosts_summary=hosts_summary,
        )

    async def _validate_playbook_exists(self, playbook_path: str) -> Path:
        """Validate that playbook file exists.

        Args:
            playbook_path: Path to playbook (relative or absolute)

        Returns:
            Resolved Path object

        Raises:
            PlaybookNotFoundError: If playbook file does not exist
        """
        # Try as absolute path first
        playbook = Path(playbook_path).expanduser()

        # If not absolute or doesn't exist, try relative to repo_path
        if not playbook.is_absolute() or not playbook.exists():
            playbook = self.repo_path / playbook_path

        if not playbook.exists():
            raise PlaybookNotFoundError(
                f"Playbook not found: {playbook_path} "
                f"(searched: {playbook} and relative to {self.repo_path})"
            )

        return playbook.resolve()

    def _is_complex_extravars(self, extravars: dict[str, Any]) -> bool:
        """Determine if extravars are complex enough to require file-based passing.

        Complex extravars include nested dicts, lists, or large data structures
        that may exceed command-line length limits.

        Args:
            extravars: Extra variables dict

        Returns:
            True if extravars should be passed via file
        """
        # Check for nested structures
        for value in extravars.values():
            if isinstance(value, (dict, list)):
                return True

        # Check for large number of variables (>10 vars = use file)
        if len(extravars) > 10:
            return True

        return False

    async def _write_extravars_file(self, extravars: dict[str, Any]) -> str:
        """Write extravars to temporary JSON file for file-based passing.

        Args:
            extravars: Extra variables dict

        Returns:
            Path to temporary JSON file
        """
        # Create temp file
        fd, temp_path = tempfile.mkstemp(suffix=".json", prefix="chiffon_extravars_")

        try:
            with open(fd, "w") as f:
                json.dump(extravars, f, indent=2)

            logger.debug(f"Wrote extravars to temp file: {temp_path}")
            return temp_path

        except Exception as e:
            # Cleanup on error
            if Path(temp_path).exists():
                Path(temp_path).unlink()
            raise AnsibleRunnerError(f"Failed to write extravars file: {e}") from e
