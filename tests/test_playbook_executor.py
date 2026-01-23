"""Tests for PlaybookExecutor service.

Comprehensive test suite covering:
- ExecutionSummary model validation
- PlaybookExecutor initialization
- Playbook validation (missing playbooks, paths)
- Playbook execution (success, failure, timeout)
- Event processing (task counts, error extraction, duration calculation)
- InfraAgent integration (work_type dispatch, error handling)

All tests use mocked ansible-runner to avoid CI dependencies.
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.agents.infra_agent.agent import InfraAgent
from src.agents.infra_agent.executor import (
    AnsibleRunnerError,
    ExecutionSummary,
    ExecutionTimeoutError,
    PlaybookExecutor,
    PlaybookNotFoundError,
)
from src.common.config import Config
from src.common.protocol import WorkRequest


# Test data fixtures
@pytest.fixture
def temp_repo_path(tmp_path):
    """Create temporary repository path with sample playbook."""
    repo = tmp_path / "ansible"
    repo.mkdir()

    # Create sample playbook
    playbook = repo / "test.yml"
    playbook.write_text(
        """
---
- name: Test playbook
  hosts: all
  tasks:
    - name: Test task
      debug:
        msg: "Hello"
"""
    )

    return repo


@pytest.fixture
def mock_ansible_runner_success():
    """Mock successful ansible-runner execution."""
    runner = MagicMock()
    runner.rc = 0
    runner.status = "successful"
    runner.events = [
        {"event": "runner_on_ok", "event_data": {"task": "Test task", "res": {"changed": True}}},
        {
            "event": "runner_on_ok",
            "event_data": {"task": "Another task", "res": {"changed": False}},
        },
    ]
    runner.stats = {"localhost": {"ok": 2, "changed": 1, "failures": 0, "skipped": 0}}
    return runner


@pytest.fixture
def mock_ansible_runner_failure():
    """Mock failed ansible-runner execution."""
    runner = MagicMock()
    runner.rc = 2
    runner.status = "failed"
    runner.events = [
        {"event": "runner_on_ok", "event_data": {"task": "Setup task", "res": {"changed": False}}},
        {
            "event": "runner_on_failed",
            "event_data": {
                "task": "Failed task",
                "res": {"msg": "Command execution failed", "stderr": "Permission denied"},
            },
        },
    ]
    runner.stats = {"localhost": {"ok": 1, "changed": 0, "failures": 1, "skipped": 0}}
    return runner


# Test ExecutionSummary model
class TestExecutionSummary:
    """Test ExecutionSummary Pydantic model."""

    def test_valid_summary(self):
        """Test creating valid ExecutionSummary."""
        summary = ExecutionSummary(
            status="successful",
            exit_code=0,
            duration_ms=1500,
            changed_count=2,
            ok_count=5,
            failed_count=0,
            skipped_count=1,
        )

        assert summary.status == "successful"
        assert summary.exit_code == 0
        assert summary.duration_ms == 1500
        assert summary.changed_count == 2

    def test_key_errors_max_length(self):
        """Test key_errors limited to max 5 entries."""
        # Pydantic validates max_length, so we can only pass up to 5 errors
        errors = [f"Error {i}" for i in range(5)]
        summary = ExecutionSummary(status="failed", exit_code=1, duration_ms=500, key_errors=errors)

        assert len(summary.key_errors) == 5

        # Verify that passing more than 5 errors raises validation error
        with pytest.raises(Exception):  # Pydantic ValidationError
            ExecutionSummary(
                status="failed",
                exit_code=1,
                duration_ms=500,
                key_errors=[f"Error {i}" for i in range(10)],
            )

    def test_default_values(self):
        """Test default values for optional fields."""
        summary = ExecutionSummary(status="successful", exit_code=0, duration_ms=1000)

        assert summary.changed_count == 0
        assert summary.ok_count == 0
        assert summary.failed_count == 0
        assert summary.skipped_count == 0
        assert summary.failed_tasks == []
        assert summary.key_errors == []
        assert summary.hosts_summary == {}


# Test PlaybookExecutor initialization
class TestPlaybookExecutorInit:
    """Test PlaybookExecutor initialization."""

    def test_init_valid_repo_path(self, temp_repo_path):
        """Test initialization with valid repository path."""
        executor = PlaybookExecutor(str(temp_repo_path))

        assert executor.repo_path == temp_repo_path.resolve()
        assert executor.artifact_retention == 10

    def test_init_custom_artifact_retention(self, temp_repo_path):
        """Test initialization with custom artifact retention."""
        executor = PlaybookExecutor(str(temp_repo_path), artifact_retention=5)

        assert executor.artifact_retention == 5

    def test_init_invalid_repo_path(self):
        """Test initialization with non-existent repository path."""
        with pytest.raises(ValueError, match="Repository path does not exist"):
            PlaybookExecutor("/nonexistent/path")

    def test_init_expands_user_path(self, temp_repo_path):
        """Test initialization expands ~ in paths."""
        # This test assumes temp_repo_path doesn't contain ~
        # But tests that expanduser() is called
        executor = PlaybookExecutor(str(temp_repo_path))
        assert executor.repo_path.is_absolute()


# Test playbook validation
class TestPlaybookExecutorValidation:
    """Test playbook path validation."""

    @pytest.mark.asyncio
    async def test_validate_missing_playbook(self, temp_repo_path):
        """Test validation raises PlaybookNotFoundError for missing playbook."""
        executor = PlaybookExecutor(str(temp_repo_path))

        with pytest.raises(PlaybookNotFoundError, match="Playbook not found"):
            await executor._validate_playbook_exists("nonexistent.yml")

    @pytest.mark.asyncio
    async def test_validate_existing_playbook(self, temp_repo_path):
        """Test validation succeeds for existing playbook."""
        executor = PlaybookExecutor(str(temp_repo_path))

        validated_path = await executor._validate_playbook_exists("test.yml")
        assert validated_path.exists()
        assert validated_path.name == "test.yml"

    @pytest.mark.asyncio
    async def test_validate_absolute_path(self, temp_repo_path):
        """Test validation with absolute path."""
        executor = PlaybookExecutor(str(temp_repo_path))
        playbook_path = temp_repo_path / "test.yml"

        validated_path = await executor._validate_playbook_exists(str(playbook_path))
        assert validated_path == playbook_path.resolve()

    @pytest.mark.asyncio
    async def test_validate_relative_path(self, temp_repo_path):
        """Test validation with relative path."""
        executor = PlaybookExecutor(str(temp_repo_path))

        validated_path = await executor._validate_playbook_exists("test.yml")
        assert validated_path.name == "test.yml"


# Test playbook execution
class TestPlaybookExecutorExecution:
    """Test playbook execution with mocked ansible-runner."""

    @pytest.mark.asyncio
    async def test_execute_success(
        self, temp_repo_path, mock_ansible_runner_success, mock_ansible_runner
    ):
        """Test successful playbook execution."""
        executor = PlaybookExecutor(str(temp_repo_path))

        with patch("ansible_runner.run", return_value=mock_ansible_runner_success):
            summary = await executor.execute_playbook("test.yml")

        assert summary.status == "successful"
        assert summary.exit_code == 0
        assert summary.changed_count == 1
        assert summary.ok_count == 2
        assert summary.failed_count == 0

    @pytest.mark.asyncio
    async def test_execute_failure(
        self, temp_repo_path, mock_ansible_runner_failure, mock_ansible_runner
    ):
        """Test failed playbook execution."""
        executor = PlaybookExecutor(str(temp_repo_path))

        with patch("ansible_runner.run", return_value=mock_ansible_runner_failure):
            summary = await executor.execute_playbook("test.yml")

        assert summary.status == "failed"
        assert summary.exit_code == 2
        assert summary.failed_count == 1
        assert len(summary.failed_tasks) == 1
        assert summary.failed_tasks[0] == "Failed task"

    @pytest.mark.asyncio
    async def test_execute_timeout(self, temp_repo_path):
        """Test playbook execution timeout."""
        executor = PlaybookExecutor(str(temp_repo_path))

        # Mock _run_ansible_sync to sleep longer than timeout
        def slow_run(cfg):
            import time

            time.sleep(2)
            return MagicMock(rc=0, status="successful", events=[], stats={})

        with patch.object(executor, "_run_ansible_sync", side_effect=slow_run):
            with pytest.raises(ExecutionTimeoutError, match="exceeded.*timeout"):
                await executor.execute_playbook("test.yml", timeout_seconds=0.1)

    @pytest.mark.asyncio
    async def test_execute_with_extravars(
        self, temp_repo_path, mock_ansible_runner_success, mock_ansible_runner
    ):
        """Test playbook execution with extravars."""
        executor = PlaybookExecutor(str(temp_repo_path))
        extravars = {"var1": "value1", "var2": "value2"}

        with patch("ansible_runner.run", return_value=mock_ansible_runner_success) as mock_run:
            await executor.execute_playbook("test.yml", extravars=extravars)

        # Verify extravars were passed to ansible-runner
        call_kwargs = mock_run.call_args[1]
        assert "extravars" in call_kwargs or "cmdline" in call_kwargs

    @pytest.mark.asyncio
    async def test_execute_with_inventory(
        self, temp_repo_path, mock_ansible_runner_success, mock_ansible_runner
    ):
        """Test playbook execution with custom inventory."""
        executor = PlaybookExecutor(str(temp_repo_path))

        with patch("ansible_runner.run", return_value=mock_ansible_runner_success) as mock_run:
            await executor.execute_playbook("test.yml", inventory="production")

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["inventory"] == "production"

    @pytest.mark.asyncio
    async def test_execute_with_tags(
        self, temp_repo_path, mock_ansible_runner_success, mock_ansible_runner
    ):
        """Test playbook execution with tags."""
        executor = PlaybookExecutor(str(temp_repo_path))

        with patch("ansible_runner.run", return_value=mock_ansible_runner_success) as mock_run:
            await executor.execute_playbook("test.yml", tags=["deploy", "config"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["tags"] == "deploy,config"

    @pytest.mark.asyncio
    async def test_execute_with_limit(
        self, temp_repo_path, mock_ansible_runner_success, mock_ansible_runner
    ):
        """Test playbook execution with host limit."""
        executor = PlaybookExecutor(str(temp_repo_path))

        with patch("ansible_runner.run", return_value=mock_ansible_runner_success) as mock_run:
            await executor.execute_playbook("test.yml", limit="webservers")

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["limit"] == "webservers"

    @pytest.mark.asyncio
    async def test_execute_missing_playbook(self, temp_repo_path):
        """Test execution raises PlaybookNotFoundError for missing playbook."""
        executor = PlaybookExecutor(str(temp_repo_path))

        with pytest.raises(PlaybookNotFoundError):
            await executor.execute_playbook("nonexistent.yml")

    @pytest.mark.asyncio
    async def test_execute_ansible_runner_error(self, temp_repo_path, mock_ansible_runner):
        """Test execution handles ansible-runner internal errors."""
        executor = PlaybookExecutor(str(temp_repo_path))

        with patch("ansible_runner.run", side_effect=Exception("Ansible internal error")):
            with pytest.raises(AnsibleRunnerError, match="Ansible-runner execution failed"):
                await executor.execute_playbook("test.yml")


# Test event processing
class TestEventProcessing:
    """Test ansible-runner event processing."""

    def test_process_events_success(self, temp_repo_path, mock_ansible_runner_success):
        """Test processing successful execution events."""
        executor = PlaybookExecutor(str(temp_repo_path))

        start_time = datetime.utcnow()
        end_time = datetime.utcnow()
        summary = executor._process_events(mock_ansible_runner_success, start_time, end_time)

        assert summary.status == "successful"
        assert summary.ok_count == 2
        assert summary.changed_count == 1
        assert summary.failed_count == 0

    def test_process_events_failure(self, temp_repo_path, mock_ansible_runner_failure):
        """Test processing failed execution events."""
        executor = PlaybookExecutor(str(temp_repo_path))

        start_time = datetime.utcnow()
        end_time = datetime.utcnow()
        summary = executor._process_events(mock_ansible_runner_failure, start_time, end_time)

        assert summary.status == "failed"
        assert summary.failed_count == 1
        assert len(summary.failed_tasks) == 1
        assert "Failed task" in summary.failed_tasks[0]

    def test_process_events_extract_errors(self, temp_repo_path, mock_ansible_runner_failure):
        """Test error message extraction from events."""
        executor = PlaybookExecutor(str(temp_repo_path))

        start_time = datetime.utcnow()
        end_time = datetime.utcnow()
        summary = executor._process_events(mock_ansible_runner_failure, start_time, end_time)

        assert len(summary.key_errors) >= 1
        assert "Failed task" in summary.key_errors[0]

    def test_process_events_max_errors(self, temp_repo_path):
        """Test key_errors limited to 5 entries."""
        executor = PlaybookExecutor(str(temp_repo_path))

        # Create runner with 10 failed tasks
        runner = MagicMock()
        runner.rc = 1
        runner.events = [
            {
                "event": "runner_on_failed",
                "event_data": {"task": f"Failed task {i}", "res": {"msg": f"Error {i}"}},
            }
            for i in range(10)
        ]
        runner.stats = {}

        start_time = datetime.utcnow()
        end_time = datetime.utcnow()
        summary = executor._process_events(runner, start_time, end_time)

        assert len(summary.key_errors) == 5

    def test_process_events_calculate_duration(self, temp_repo_path, mock_ansible_runner_success):
        """Test duration calculation from start/end times."""
        executor = PlaybookExecutor(str(temp_repo_path))

        start_time = datetime(2024, 1, 1, 12, 0, 0)
        end_time = datetime(2024, 1, 1, 12, 0, 5)  # 5 seconds later
        summary = executor._process_events(mock_ansible_runner_success, start_time, end_time)

        assert summary.duration_ms == 5000

    def test_process_events_hosts_summary(self, temp_repo_path, mock_ansible_runner_success):
        """Test host summary extraction from runner stats."""
        executor = PlaybookExecutor(str(temp_repo_path))

        start_time = datetime.utcnow()
        end_time = datetime.utcnow()
        summary = executor._process_events(mock_ansible_runner_success, start_time, end_time)

        assert "localhost" in summary.hosts_summary
        assert summary.hosts_summary["localhost"]["ok"] == 2
        assert summary.hosts_summary["localhost"]["changed"] == 1


# Test complex extravars handling
class TestComplexExtravars:
    """Test complex extravars handling (file-based passing)."""

    def test_is_complex_extravars_simple(self, temp_repo_path):
        """Test simple extravars not considered complex."""
        executor = PlaybookExecutor(str(temp_repo_path))

        simple_vars = {"var1": "value1", "var2": "value2"}
        assert not executor._is_complex_extravars(simple_vars)

    def test_is_complex_extravars_nested_dict(self, temp_repo_path):
        """Test nested dict considered complex."""
        executor = PlaybookExecutor(str(temp_repo_path))

        nested_vars = {"config": {"key": "value"}}
        assert executor._is_complex_extravars(nested_vars)

    def test_is_complex_extravars_list(self, temp_repo_path):
        """Test list values considered complex."""
        executor = PlaybookExecutor(str(temp_repo_path))

        list_vars = {"items": ["item1", "item2"]}
        assert executor._is_complex_extravars(list_vars)

    def test_is_complex_extravars_many_vars(self, temp_repo_path):
        """Test >10 variables considered complex."""
        executor = PlaybookExecutor(str(temp_repo_path))

        many_vars = {f"var{i}": f"value{i}" for i in range(15)}
        assert executor._is_complex_extravars(many_vars)

    @pytest.mark.asyncio
    async def test_write_extravars_file(self, temp_repo_path):
        """Test writing extravars to temporary file."""
        executor = PlaybookExecutor(str(temp_repo_path))

        extravars = {"key1": "value1", "key2": "value2"}
        temp_file = await executor._write_extravars_file(extravars)

        try:
            assert Path(temp_file).exists()
            with open(temp_file) as f:
                data = json.load(f)
            assert data == extravars
        finally:
            if Path(temp_file).exists():
                Path(temp_file).unlink()


# Test InfraAgent integration
class TestInfraAgentExecution:
    """Test InfraAgent execute_work integration with PlaybookExecutor."""

    @pytest.mark.asyncio
    async def test_work_type_run_playbook(
        self, temp_repo_path, mock_ansible_runner_success, mock_ansible_runner
    ):
        """Test InfraAgent handles run_playbook work type."""
        config = Config()
        agent = InfraAgent("test-agent", config, repo_path=str(temp_repo_path))

        work_request = WorkRequest(
            task_id=uuid4(), work_type="run_playbook", parameters={"playbook_path": "test.yml"}
        )

        with patch("ansible_runner.run", return_value=mock_ansible_runner_success):
            result = await agent.execute_work(work_request)

        assert result.status == "completed"
        assert result.exit_code == 0
        assert "Status: successful" in result.output

    @pytest.mark.asyncio
    async def test_work_type_deploy_service(self, temp_repo_path):
        """Test InfraAgent handles deploy_service work type."""
        config = Config()
        agent = InfraAgent("test-agent", config, repo_path=str(temp_repo_path))

        work_request = WorkRequest(
            task_id=uuid4(),
            work_type="deploy_service",
            parameters={"task_intent": "deploy test service"},
        )

        # This will fail due to no matching playbook, which is expected
        result = await agent.execute_work(work_request)

        # Should fail gracefully with proper error message
        assert result.status == "failed"
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_work_type_discover_playbooks(self, temp_repo_path):
        """Test InfraAgent handles discover_playbooks work type."""
        config = Config()
        agent = InfraAgent("test-agent", config, repo_path=str(temp_repo_path))

        work_request = WorkRequest(
            task_id=uuid4(), work_type="discover_playbooks", parameters={"force_refresh": False}
        )

        result = await agent.execute_work(work_request)

        # If failed, print error message for debugging
        if result.status == "failed":
            print(f"Error: {result.error_message}")
            print(f"Output: {result.output}")

        assert result.status == "completed"
        assert result.exit_code == 0
        # Output should be JSON catalog
        catalog = json.loads(result.output)
        assert isinstance(catalog, list)

    @pytest.mark.asyncio
    async def test_work_type_unknown(self, temp_repo_path):
        """Test InfraAgent handles unknown work type gracefully."""
        config = Config()
        agent = InfraAgent("test-agent", config, repo_path=str(temp_repo_path))

        work_request = WorkRequest(task_id=uuid4(), work_type="invalid_work_type", parameters={})

        result = await agent.execute_work(work_request)

        assert result.status == "failed"
        assert "Unknown work type" in result.error_message

    @pytest.mark.asyncio
    async def test_error_handling_missing_playbook(self, temp_repo_path):
        """Test InfraAgent handles PlaybookNotFoundError."""
        config = Config()
        agent = InfraAgent("test-agent", config, repo_path=str(temp_repo_path))

        work_request = WorkRequest(
            task_id=uuid4(),
            work_type="run_playbook",
            parameters={"playbook_path": "nonexistent.yml"},
        )

        result = await agent.execute_work(work_request)

        assert result.status == "failed"
        assert result.exit_code == 2
        assert "Playbook not found" in result.error_message

    @pytest.mark.asyncio
    async def test_error_handling_timeout(self, temp_repo_path):
        """Test InfraAgent handles ExecutionTimeoutError."""
        config = Config()
        agent = InfraAgent("test-agent", config, repo_path=str(temp_repo_path))

        work_request = WorkRequest(
            task_id=uuid4(),
            work_type="run_playbook",
            parameters={"playbook_path": "test.yml", "timeout_seconds": 0.1},
        )

        def slow_run(cfg):
            import time

            time.sleep(2)
            return MagicMock(rc=0, status="successful", events=[], stats={})

        with patch.object(agent.executor, "_run_ansible_sync", side_effect=slow_run):
            result = await agent.execute_work(work_request)

        assert result.status == "failed"
        assert result.exit_code == 124  # Timeout exit code
        assert "timeout" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_summary_to_result_conversion(self, temp_repo_path, mock_ansible_runner_success):
        """Test _summary_to_result converts ExecutionSummary to WorkResult."""
        config = Config()
        agent = InfraAgent("test-agent", config, repo_path=str(temp_repo_path))

        executor = PlaybookExecutor(str(temp_repo_path))
        start_time = datetime.utcnow()
        end_time = datetime.utcnow()
        summary = executor._process_events(mock_ansible_runner_success, start_time, end_time)

        task_id = uuid4()
        result = await agent._summary_to_result(task_id, summary, "test.yml")

        assert result.task_id == task_id
        assert result.status == "completed"
        assert "Status: successful" in result.output
        assert "Tasks:" in result.output
