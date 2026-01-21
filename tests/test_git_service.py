"""Comprehensive test suite for GitService and integration.

Tests:
- GitService initialization
- Audit entry formatting
- Git commits and idempotency
- Error handling
- Integration with OrchestratorService
"""

import json
import logging
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.common.models import Task
from src.orchestrator.git_service import GitService, GitServiceError

logger = logging.getLogger(__name__)


# ==================== Fixtures ====================


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository for testing.

    Yields:
        Path to temporary git repository
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_path = Path(tmp_dir)

        # Initialize git repo
        subprocess.run(
            ["git", "init"],
            cwd=str(repo_path),
            capture_output=True,
            check=True,
        )

        # Configure git user for commits
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=str(repo_path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=str(repo_path),
            capture_output=True,
            check=True,
        )

        yield repo_path


@pytest.fixture
def mock_task():
    """Create a mock Task object for testing.

    Returns:
        Mock Task with required fields
    """
    task = MagicMock(spec=Task)
    task.task_id = uuid4()
    task.status = "completed"
    task.created_at = datetime.utcnow()
    task.completed_at = datetime.utcnow()
    task.outcome = {"success": True, "message": "Task completed"}
    task.actual_resources = {"duration_ms": 1000, "exit_code": 0}
    task.services_touched = ["kuma", "portainer"]
    task.plan_id = "plan-001"
    task.plan_steps = ["step1", "step2"]
    task.agent_pool = "infra_pool_1"
    task.agent_id = str(uuid4())
    task.dispatch_timestamp = datetime.utcnow().isoformat() + "Z"
    return task


@pytest.fixture
def git_service(temp_git_repo):
    """Create GitService instance with temporary repo.

    Args:
        temp_git_repo: Temporary git repo fixture

    Returns:
        GitService instance
    """
    return GitService(repo_path=str(temp_git_repo))


# ==================== TestGitServiceInitialization ====================


class TestGitServiceInitialization:
    """Test GitService initialization and configuration."""

    def test_init_with_valid_repo_path(self, temp_git_repo):
        """Test initialization with valid git repo path."""
        service = GitService(repo_path=str(temp_git_repo))
        assert service.repo_path == temp_git_repo
        assert service.audit_dir == temp_git_repo / ".audit" / "tasks"

    def test_init_creates_audit_directory(self, temp_git_repo):
        """Test that init creates .audit/tasks directory if missing."""
        service = GitService(repo_path=str(temp_git_repo))
        assert service.audit_dir.exists()
        assert service.audit_dir.is_dir()

    def test_init_with_existing_audit_directory(self, temp_git_repo):
        """Test init succeeds when audit directory already exists."""
        # Pre-create audit directory
        (temp_git_repo / ".audit" / "tasks").mkdir(parents=True, exist_ok=True)
        service = GitService(repo_path=str(temp_git_repo))
        assert service.audit_dir.exists()

    def test_init_with_invalid_path(self):
        """Test initialization fails with invalid repo path."""
        with pytest.raises(GitServiceError, match="does not exist"):
            GitService(repo_path="/nonexistent/path/to/repo")

    def test_init_default_repo_path(self, monkeypatch):
        """Test initialization with default repo path."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            monkeypatch.chdir(tmp_dir)
            subprocess.run(["git", "init"], capture_output=True, check=True)
            service = GitService()
            assert service.repo_path == Path(tmp_dir).resolve()


# ==================== TestAuditEntryFormatting ====================


class TestAuditEntryFormatting:
    """Test audit entry JSON format and structure."""

    @pytest.mark.asyncio
    async def test_audit_entry_has_required_fields(self, git_service, mock_task):
        """Test that audit entry contains all required fields."""
        # Mock subprocess to avoid actual git commit
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            await git_service.commit_task_outcome(mock_task)

            # Read audit file
            audit_file = git_service.audit_dir / f"{mock_task.task_id}.json"
            with open(audit_file) as f:
                audit_entry = json.load(f)

            # Verify required fields
            assert "task_id" in audit_entry
            assert "status" in audit_entry
            assert "plan_id" in audit_entry
            assert "plan_steps" in audit_entry
            assert "dispatch_info" in audit_entry
            assert "execution_result" in audit_entry
            assert "timestamp" in audit_entry

    @pytest.mark.asyncio
    async def test_audit_entry_timestamp_format(self, git_service, mock_task):
        """Test that audit entry has valid ISO8601 timestamp."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            await git_service.commit_task_outcome(mock_task)

            audit_file = git_service.audit_dir / f"{mock_task.task_id}.json"
            with open(audit_file) as f:
                audit_entry = json.load(f)

            # Verify timestamp is ISO8601 format with Z suffix
            timestamp = audit_entry["timestamp"]
            assert timestamp.endswith("Z")
            # Try parsing as ISO8601
            datetime.fromisoformat(timestamp.rstrip("Z"))

    @pytest.mark.asyncio
    async def test_audit_entry_dispatch_info(self, git_service, mock_task):
        """Test dispatch_info contains expected fields."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            await git_service.commit_task_outcome(mock_task)

            audit_file = git_service.audit_dir / f"{mock_task.task_id}.json"
            with open(audit_file) as f:
                audit_entry = json.load(f)

            dispatch_info = audit_entry["dispatch_info"]
            assert "agent_pool" in dispatch_info
            assert "agent_id" in dispatch_info
            assert "dispatch_timestamp" in dispatch_info

    @pytest.mark.asyncio
    async def test_audit_entry_execution_result(self, git_service, mock_task):
        """Test execution_result contains expected fields."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            await git_service.commit_task_outcome(mock_task)

            audit_file = git_service.audit_dir / f"{mock_task.task_id}.json"
            with open(audit_file) as f:
                audit_entry = json.load(f)

            exec_result = audit_entry["execution_result"]
            assert "outcome" in exec_result
            assert "resources_used" in exec_result
            assert "services_touched" in exec_result
            assert "start_time" in exec_result
            assert "end_time" in exec_result

    @pytest.mark.asyncio
    async def test_audit_entry_json_valid(self, git_service, mock_task):
        """Test that audit entry is valid JSON."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            await git_service.commit_task_outcome(mock_task)

            audit_file = git_service.audit_dir / f"{mock_task.task_id}.json"

            # Should parse without error
            with open(audit_file) as f:
                audit_entry = json.load(f)

            # Verify it's a dict
            assert isinstance(audit_entry, dict)


# ==================== TestCommitAuditEntry ====================


class TestCommitAuditEntry:
    """Test git commit creation for audit entries."""

    @pytest.mark.asyncio
    async def test_new_commit_creates_file(self, git_service, mock_task):
        """Test that new commit creates audit entry file."""
        audit_file = git_service.audit_dir / f"{mock_task.task_id}.json"
        assert not audit_file.exists()

        await git_service.commit_task_outcome(mock_task)

        assert audit_file.exists()

    @pytest.mark.asyncio
    async def test_new_commit_calls_git_add(self, git_service, mock_task):
        """Test that commit calls git add with correct path."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            await git_service.commit_task_outcome(mock_task)

            # Verify git add was called
            git_add_calls = [
                call for call in mock_run.call_args_list
                if "add" in str(call)
            ]
            assert len(git_add_calls) > 0

    @pytest.mark.asyncio
    async def test_new_commit_calls_git_commit(self, git_service, mock_task):
        """Test that commit calls git commit with proper message."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            await git_service.commit_task_outcome(mock_task)

            # Verify git commit was called
            git_commit_calls = [
                call for call in mock_run.call_args_list
                if "commit" in str(call)
            ]
            assert len(git_commit_calls) > 0

    @pytest.mark.asyncio
    async def test_commit_returns_true_on_new_file(self, git_service, mock_task):
        """Test that commit returns True when creating new audit entry."""
        result = await git_service.commit_task_outcome(mock_task)
        assert result is True

    @pytest.mark.asyncio
    async def test_commit_message_format(self, git_service, mock_task):
        """Test commit message includes task_id and status."""
        await git_service.commit_task_outcome(mock_task)

        # Check git log
        result = subprocess.run(
            ["git", "log", "--oneline", ".audit/tasks/"],
            cwd=str(git_service.repo_path),
            capture_output=True,
            text=True,
            check=True,
        )

        log_output = result.stdout
        assert "audit:" in log_output
        assert str(mock_task.task_id) in log_output
        assert mock_task.status in log_output


# ==================== TestIdempotency ====================


class TestIdempotency:
    """Test idempotency of audit commits."""

    @pytest.mark.asyncio
    async def test_re_commit_same_task_returns_false(self, git_service, mock_task):
        """Test that re-committing same task returns False."""
        # First commit
        result1 = await git_service.commit_task_outcome(mock_task)
        assert result1 is True

        # Second commit (should skip)
        result2 = await git_service.commit_task_outcome(mock_task)
        assert result2 is False

    @pytest.mark.asyncio
    async def test_audit_file_already_exists_check(self, git_service, mock_task):
        """Test idempotency check detects existing audit file."""
        # Create audit file manually
        audit_file = git_service.audit_dir / f"{mock_task.task_id}.json"
        audit_file.write_text('{"test": "data"}')

        # Attempt commit
        result = await git_service.commit_task_outcome(mock_task)

        # Should skip
        assert result is False

    @pytest.mark.asyncio
    async def test_multiple_commits_no_duplicates(self, git_service, mock_task):
        """Test that multiple commits don't create duplicate git entries."""
        # First commit
        await git_service.commit_task_outcome(mock_task)

        # Second commit (should skip)
        await git_service.commit_task_outcome(mock_task)

        # Check git log - should have only one commit for this task
        result = subprocess.run(
            ["git", "log", "--oneline", ".audit/tasks/"],
            cwd=str(git_service.repo_path),
            capture_output=True,
            text=True,
            check=True,
        )

        # Count commits mentioning this task_id
        commit_count = result.stdout.count(str(mock_task.task_id))
        assert commit_count == 1


# ==================== TestErrorHandling ====================


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_graceful_handling_missing_git_directory(self, temp_git_repo):
        """Test graceful handling when .git directory is missing."""
        # Remove .git directory
        import shutil
        git_dir = temp_git_repo / ".git"
        shutil.rmtree(git_dir)

        service = GitService(repo_path=str(temp_git_repo))

        # Should still initialize (no error)
        assert service.repo_path == temp_git_repo

    @pytest.mark.asyncio
    async def test_error_when_git_command_fails(self, git_service, mock_task):
        """Test error when git command fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "git")

            with pytest.raises(GitServiceError):
                await git_service.commit_task_outcome(mock_task)

    @pytest.mark.asyncio
    async def test_error_when_task_missing_task_id(self, git_service):
        """Test error when Task missing task_id."""
        task = MagicMock(spec=Task)
        task.task_id = None
        task.status = "completed"

        with pytest.raises(GitServiceError, match="task_id"):
            await git_service.commit_task_outcome(task)

    @pytest.mark.asyncio
    async def test_error_when_task_missing_status(self, git_service):
        """Test error when Task missing status."""
        task = MagicMock(spec=Task)
        task.task_id = uuid4()
        task.status = None

        with pytest.raises(GitServiceError, match="status"):
            await git_service.commit_task_outcome(task)

    @pytest.mark.asyncio
    async def test_git_service_error_exception_class(self, git_service, mock_task):
        """Test that GitServiceError is raised on git failures."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="git error")

            with pytest.raises(GitServiceError):
                await git_service.commit_task_outcome(mock_task)


# ==================== TestGitCommandGeneration ====================


class TestGitCommandGeneration:
    """Test correct git command generation."""

    @pytest.mark.asyncio
    async def test_git_add_command_uses_correct_path(self, git_service, mock_task):
        """Test that git add uses correct audit file path."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            await git_service.commit_task_outcome(mock_task)

            # Find git add call
            add_call = None
            for call in mock_run.call_args_list:
                if "add" in str(call):
                    add_call = call
                    break

            assert add_call is not None
            # Verify audit file path in call args
            call_args = str(add_call)
            audit_file = git_service.audit_dir / f"{mock_task.task_id}.json"
            assert str(audit_file) in call_args

    @pytest.mark.asyncio
    async def test_git_commit_message_format(self, git_service, mock_task):
        """Test git commit message format."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            await git_service.commit_task_outcome(mock_task)

            # Find git commit call
            commit_call = None
            for call in mock_run.call_args_list:
                if "commit" in str(call):
                    commit_call = call
                    break

            assert commit_call is not None
            call_args = str(commit_call)
            # Message should contain audit prefix, task_id, and status
            assert "audit:" in call_args
            assert str(mock_task.task_id) in call_args
            assert mock_task.status in call_args

    @pytest.mark.asyncio
    async def test_subprocess_run_uses_capture_output(self, git_service, mock_task):
        """Test that subprocess calls use capture_output=True."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            await git_service.commit_task_outcome(mock_task)

            # All subprocess.run calls should use capture_output=True
            for call in mock_run.call_args_list:
                kwargs = call[1]
                assert kwargs.get("capture_output") is True

    @pytest.mark.asyncio
    async def test_subprocess_run_uses_cwd(self, git_service, mock_task):
        """Test that subprocess calls set cwd to repo_path."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            await git_service.commit_task_outcome(mock_task)

            # All subprocess.run calls should use cwd=repo_path
            for call in mock_run.call_args_list:
                kwargs = call[1]
                assert kwargs.get("cwd") == str(git_service.repo_path)


# ==================== TestIntegrationWithOrchestratorService ====================


class TestIntegrationWithOrchestratorService:
    """Test integration with OrchestratorService."""

    @pytest.mark.asyncio
    async def test_orchestrator_service_imports_git_service(self):
        """Test that OrchestratorService can import GitService."""
        from src.orchestrator.service import OrchestratorService
        from src.orchestrator.git_service import GitService

        # Verify import succeeded
        assert OrchestratorService is not None
        assert GitService is not None

    @pytest.mark.asyncio
    async def test_orchestrator_service_initializes_git_service(self, temp_git_repo):
        """Test that OrchestratorService initializes GitService in __init__."""
        from src.orchestrator.service import OrchestratorService
        from src.common.config import Config
        from unittest.mock import MagicMock

        # Create mock config and db_session
        config = MagicMock(spec=Config)
        db_session = MagicMock()

        # Create orchestrator with repo_path
        orchestrator = OrchestratorService(
            config=config,
            db_session=db_session,
            repo_path=str(temp_git_repo),
        )

        # Verify git_service initialized
        assert hasattr(orchestrator, "git_service")
        assert orchestrator.git_service is not None

    @pytest.mark.asyncio
    async def test_git_commit_on_task_completion(self, temp_git_repo, mock_task):
        """Test that git commit happens on task completion."""
        from src.orchestrator.service import OrchestratorService
        from src.common.config import Config
        from src.common.protocol import WorkResult
        from unittest.mock import MagicMock, AsyncMock

        # Create orchestrator
        config = MagicMock(spec=Config)
        db_session = MagicMock()

        orchestrator = OrchestratorService(
            config=config,
            db_session=db_session,
            repo_path=str(temp_git_repo),
        )

        # Mock database query to return our mock task
        db_session.query.return_value.filter.return_value.first.return_value = mock_task

        # Create work result
        work_result = WorkResult(
            task_id=mock_task.task_id,
            status="completed",
            error_message=None,
            duration_ms=1000,
            exit_code=0,
        )

        # Handle work result
        await orchestrator.handle_work_result(work_result, uuid4())

        # Verify audit entry was created
        audit_file = temp_git_repo / ".audit" / "tasks" / f"{mock_task.task_id}.json"
        assert audit_file.exists()

    @pytest.mark.asyncio
    async def test_failed_tasks_also_committed(self, temp_git_repo, mock_task):
        """Test that failed tasks are also committed to git."""
        from src.orchestrator.service import OrchestratorService
        from src.common.config import Config
        from src.common.protocol import WorkResult
        from unittest.mock import MagicMock

        config = MagicMock(spec=Config)
        db_session = MagicMock()

        orchestrator = OrchestratorService(
            config=config,
            db_session=db_session,
            repo_path=str(temp_git_repo),
        )

        mock_task.status = "failed"
        db_session.query.return_value.filter.return_value.first.return_value = mock_task

        work_result = WorkResult(
            task_id=mock_task.task_id,
            status="failed",
            error_message="Task failed",
            duration_ms=500,
            exit_code=1,
        )

        await orchestrator.handle_work_result(work_result, uuid4())

        # Verify audit entry exists for failed task
        audit_file = temp_git_repo / ".audit" / "tasks" / f"{mock_task.task_id}.json"
        assert audit_file.exists()

    @pytest.mark.asyncio
    async def test_git_error_doesnt_block_orchestrator(self, temp_git_repo, mock_task):
        """Test that git commit errors don't block orchestrator execution."""
        from src.orchestrator.service import OrchestratorService
        from src.common.config import Config
        from src.common.protocol import WorkResult
        from unittest.mock import MagicMock, patch

        config = MagicMock(spec=Config)
        db_session = MagicMock()

        orchestrator = OrchestratorService(
            config=config,
            db_session=db_session,
            repo_path=str(temp_git_repo),
        )

        db_session.query.return_value.filter.return_value.first.return_value = mock_task

        # Patch git_service to raise error
        orchestrator.git_service.commit_task_outcome = AsyncMock(
            side_effect=Exception("git error")
        )

        work_result = WorkResult(
            task_id=mock_task.task_id,
            status="completed",
            error_message=None,
            duration_ms=1000,
            exit_code=0,
        )

        # Should not raise, even though git fails
        await orchestrator.handle_work_result(work_result, uuid4())

        # Verify database commit still happened
        db_session.commit.assert_called()


# ==================== TestParametrizedScenarios ====================


class TestParametrizedScenarios:
    """Test parametrized scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["completed", "failed", "rejected", "cancelled"])
    async def test_commit_multiple_task_statuses(self, git_service, status):
        """Test commits work for multiple task statuses."""
        task = MagicMock(spec=Task)
        task.task_id = uuid4()
        task.status = status
        task.created_at = datetime.utcnow()
        task.completed_at = datetime.utcnow()
        task.outcome = {}
        task.actual_resources = {}
        task.services_touched = []

        result = await git_service.commit_task_outcome(task)

        assert result is True
        audit_file = git_service.audit_dir / f"{task.task_id}.json"
        assert audit_file.exists()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("error_type", [
        GitServiceError("Missing git repo"),
        Exception("Unexpected error"),
    ])
    async def test_error_types(self, git_service, mock_task, error_type):
        """Test handling of various error types."""
        with patch("subprocess.run") as mock_run:
            if isinstance(error_type, GitServiceError):
                # GitServiceError should be re-raised
                mock_run.side_effect = error_type
                with pytest.raises(GitServiceError):
                    await git_service.commit_task_outcome(mock_task)
            else:
                # Other exceptions should be caught and wrapped
                mock_run.side_effect = error_type
                # GitService wraps unexpected errors
                with pytest.raises(GitServiceError):
                    await git_service.commit_task_outcome(mock_task)
