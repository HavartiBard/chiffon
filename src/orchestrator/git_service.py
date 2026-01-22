"""GitService: Immutable git audit trail for task outcomes.

Provides:
- Automatic commit of task outcomes to git
- Idempotent commits (no duplicates on re-submission)
- JSON audit entry format with full execution context
- Error handling (git failures don't block orchestrator)
"""

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.common.models import Task

logger = logging.getLogger(__name__)


class GitServiceError(Exception):
    """Exception raised by GitService for git operation failures."""

    pass


class GitService:
    """Service for committing task outcomes to git audit trail.

    Maintains an immutable audit trail by creating a git commit for each
    completed task. Commits are idempotent (re-committing same task creates
    no new commit). Failures are logged but don't block orchestrator execution.

    Attributes:
        repo_path: Path to git repository root
    """

    def __init__(self, repo_path: str = "."):
        """Initialize GitService with repository path.

        Args:
            repo_path: Path to git repository (default: "." for current dir)

        Raises:
            GitServiceError: If repo_path doesn't exist
        """
        self.repo_path = Path(repo_path).resolve()
        self.audit_dir = self.repo_path / ".audit" / "tasks"

        # Validate repo exists
        if not self.repo_path.exists():
            raise GitServiceError(f"Repository path does not exist: {repo_path}")

        # Ensure audit directory exists
        try:
            self.audit_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise GitServiceError(f"Failed to create audit directory: {e}")

        logger.info(f"GitService initialized with repo_path={self.repo_path}")

    async def commit_task_outcome(self, task: Task) -> bool:
        """Commit task outcome to git audit trail.

        Creates a JSON audit entry file for the task and commits it to git.
        Idempotent: if the audit entry already exists, skips commit and
        returns False to indicate no new commit was created.

        Args:
            task: Task object with outcome details

        Returns:
            True if new commit was created, False if skipped (already exists)

        Raises:
            GitServiceError: If required task fields are missing or git command fails
        """
        try:
            # Validate task has required fields
            if not task.task_id:
                raise GitServiceError("Task missing task_id")
            if not task.status:
                raise GitServiceError("Task missing status")

            # Check if .git directory exists
            git_dir = self.repo_path / ".git"
            if not git_dir.exists():
                logger.warning(f"Not in git repository (no .git directory at {self.repo_path})")
                return False

            # Build audit entry filename and path
            audit_file_path = self.audit_dir / f"{task.task_id}.json"

            # Idempotency check: if file already exists, skip commit
            if audit_file_path.exists():
                logger.info(f"Audit entry already exists for task {task.task_id}, skipping commit")
                return False

            # Build audit entry JSON
            timestamp_iso = datetime.utcnow().isoformat() + "Z"
            audit_entry = {
                "task_id": str(task.task_id),
                "status": task.status,
                "plan_id": getattr(task, "plan_id", None),
                "plan_steps": getattr(task, "plan_steps", []),
                "dispatch_info": {
                    "agent_pool": getattr(task, "agent_pool", None),
                    "agent_id": getattr(task, "agent_id", None),
                    "dispatch_timestamp": getattr(task, "dispatch_timestamp", None),
                },
                "execution_result": {
                    "outcome": task.outcome or {},
                    "resources_used": task.actual_resources or {},
                    "services_touched": task.services_touched or [],
                    "start_time": task.created_at.isoformat() if task.created_at else None,
                    "end_time": task.completed_at.isoformat() if task.completed_at else None,
                },
                "timestamp": timestamp_iso,
            }

            # Write audit entry JSON file
            try:
                with open(audit_file_path, "w") as f:
                    json.dump(audit_entry, f, indent=2)
                logger.info(f"Wrote audit entry to {audit_file_path}")
            except Exception as e:
                raise GitServiceError(f"Failed to write audit entry file: {e}")

            # Stage file with git add
            try:
                result = subprocess.run(
                    ["git", "add", str(audit_file_path)],
                    cwd=str(self.repo_path),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    raise GitServiceError(f"git add failed: {result.stderr or result.stdout}")
                logger.debug(f"Staged audit entry with git add: {audit_file_path}")
            except subprocess.TimeoutExpired:
                raise GitServiceError("git add command timed out")
            except Exception as e:
                raise GitServiceError(f"git add failed: {e}")

            # Commit with git commit
            commit_message = f"audit: task {task.task_id} {task.status} at {timestamp_iso}"
            try:
                result = subprocess.run(
                    ["git", "commit", "-m", commit_message],
                    cwd=str(self.repo_path),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    raise GitServiceError(f"git commit failed: {result.stderr or result.stdout}")
                logger.info(f"Committed audit entry for task {task.task_id}: {commit_message}")
            except subprocess.TimeoutExpired:
                raise GitServiceError("git commit command timed out")
            except Exception as e:
                raise GitServiceError(f"git commit failed: {e}")

            return True

        except GitServiceError as e:
            logger.error(f"GitService error for task {getattr(task, 'task_id', 'unknown')}: {e}")
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error in commit_task_outcome for task {getattr(task, 'task_id', 'unknown')}: {e}",
                exc_info=True,
            )
            raise GitServiceError(f"Unexpected error: {e}")
