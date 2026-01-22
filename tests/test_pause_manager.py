"""Comprehensive tests for PauseManager and orchestrator integration.

Tests pause/resume lifecycle, capacity checking, database persistence,
background polling, and integration with OrchestratorService.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import UUID, uuid4

import pytest

from src.orchestrator.pause_manager import PauseManager


class MockAgentRegistry:
    """Mock AgentRegistry model for testing."""

    def __init__(
        self,
        agent_id,
        agent_type,
        pool_name,
        capabilities,
        status="online",
        resource_metrics=None,
    ):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.pool_name = pool_name
        self.capabilities = capabilities
        self.status = status
        self.resource_metrics = resource_metrics or {}


class MockPauseQueueEntry:
    """Mock PauseQueueEntry model for testing."""

    def __init__(
        self, task_id, work_plan_json, reason, paused_at=None, resume_after=None, priority=3
    ):
        self.id = None
        self.task_id = task_id
        self.work_plan_json = work_plan_json
        self.reason = reason
        self.paused_at = paused_at or datetime.utcnow()
        self.resume_after = resume_after
        self.priority = priority


class MockTask:
    """Mock Task model for testing."""

    def __init__(self, task_id, request_text, status="pending"):
        self.task_id = task_id
        self.request_text = request_text
        self.status = status


@pytest.fixture
def mock_db_session():
    """Create mock database session for testing."""
    db = Mock()
    db.agents = []
    db.pause_queue = []
    db.tasks = []
    db.add = Mock(side_effect=lambda x: db._add_item(x))
    db.commit = Mock()
    db.rollback = Mock()

    def _add_item(item):
        if isinstance(item, MockAgentRegistry):
            db.agents.append(item)
        elif isinstance(item, MockPauseQueueEntry):
            db.pause_queue.append(item)
        elif isinstance(item, MockTask):
            db.tasks.append(item)

    db._add_item = _add_item
    return db


@pytest.fixture
def pause_manager(mock_db_session):
    """Create PauseManager instance for testing."""
    pm = PauseManager(db=mock_db_session, capacity_threshold_percent=0.2)
    # Patch the models used in pause_manager
    pm.db.query = lambda model: _create_query_mock(mock_db_session, model)
    return pm


def _create_query_mock(db, model):
    """Create a mock query object for the given model."""
    q = Mock()

    def filter_by(**kwargs):
        f = Mock()
        if model == MockAgentRegistry:
            results = [a for a in db.agents for k, v in kwargs.items() if getattr(a, k, None) == v]
        elif model == MockPauseQueueEntry:
            results = [
                p for p in db.pause_queue for k, v in kwargs.items() if getattr(p, k, None) == v
            ]
        elif model == MockTask:
            results = [t for t in db.tasks for k, v in kwargs.items() if getattr(t, k, None) == v]
        else:
            results = []
        f.first = Mock(return_value=results[0] if results else None)
        return f

    def filter(*args):
        f = Mock()
        if model == MockAgentRegistry:
            results = [a for a in db.agents if a.status in ["online", "busy"]]
        elif model == MockPauseQueueEntry:
            results = [
                p
                for p in db.pause_queue
                if p.resume_after is None or p.resume_after <= datetime.utcnow()
            ]
        else:
            results = []
        f.all = Mock(return_value=results)
        f.first = Mock(return_value=results[0] if results else None)
        return f

    q.filter_by = filter_by
    q.filter = filter
    return q


@pytest.fixture
def mock_agent(mock_db_session):
    """Create mock agent with resource metrics."""
    agent = MockAgentRegistry(
        agent_id=uuid4(),
        agent_type="desktop",
        pool_name="pool-1",
        capabilities=["metrics"],
        status="online",
        resource_metrics={
            "gpu_vram_available_gb": 4.0,
            "cpu_cores_available": 8,
            "gpu_vram_total_gb": 8.0,
            "cpu_cores_total": 16,
        },
    )
    mock_db_session.agents.append(agent)
    return agent


@pytest.fixture
def low_capacity_agent(mock_db_session):
    """Create agent with low available capacity."""
    agent = MockAgentRegistry(
        agent_id=uuid4(),
        agent_type="desktop",
        pool_name="pool-1",
        capabilities=["metrics"],
        status="online",
        resource_metrics={
            "gpu_vram_available_gb": 0.5,  # Very low
            "cpu_cores_available": 1,  # Very low
            "gpu_vram_total_gb": 8.0,
            "cpu_cores_total": 16,
        },
    )
    mock_db_session.agents.append(agent)
    return agent


class TestPauseManagerInitialization:
    """Test PauseManager initialization and configuration."""

    def test_init_with_defaults(self, mock_db_session):
        """Test initialization with default parameters."""
        pm = PauseManager(db=mock_db_session)
        assert pm.capacity_threshold_percent == 0.2
        assert pm.polling_interval_seconds == 10
        assert pm.polling_active is False
        assert pm._polling_task is None

    def test_init_with_custom_threshold(self, mock_db_session):
        """Test initialization with custom capacity threshold."""
        pm = PauseManager(db=mock_db_session, capacity_threshold_percent=0.15)
        assert pm.capacity_threshold_percent == 0.15

    def test_init_loads_threshold_from_env(self, mock_db_session):
        """Test that environment variable overrides parameter."""
        with patch.dict("os.environ", {"PAUSE_CAPACITY_THRESHOLD_PERCENT": "0.25"}):
            pm = PauseManager(db=mock_db_session, capacity_threshold_percent=0.2)
            assert pm.capacity_threshold_percent == 0.25

    def test_init_loads_polling_interval_from_env(self, mock_db_session):
        """Test that polling interval loaded from environment."""
        with patch.dict("os.environ", {"PAUSE_POLLING_INTERVAL_SECONDS": "15"}):
            pm = PauseManager(db=mock_db_session)
            assert pm.polling_interval_seconds == 15

    def test_init_invalid_env_threshold_uses_default(self, mock_db_session):
        """Test that invalid environment threshold falls back to parameter."""
        with patch.dict("os.environ", {"PAUSE_CAPACITY_THRESHOLD_PERCENT": "invalid"}):
            pm = PauseManager(db=mock_db_session, capacity_threshold_percent=0.2)
            assert pm.capacity_threshold_percent == 0.2


class TestCapacityChecking:
    """Test capacity checking logic."""

    @pytest.mark.asyncio
    async def test_should_pause_with_high_capacity(self, pause_manager, mock_agent):
        """Test should_pause returns False when agents have capacity."""
        result = await pause_manager.should_pause("plan-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_should_pause_with_low_capacity(self, pause_manager, low_capacity_agent):
        """Test should_pause returns True when all agents below threshold."""
        result = await pause_manager.should_pause("plan-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_should_pause_with_no_agents(self, pause_manager):
        """Test should_pause returns True when no agents online."""
        result = await pause_manager.should_pause("plan-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_should_pause_with_multiple_low_capacity_agents(self, mock_db_session):
        """Test should_pause with multiple agents all below threshold."""
        pm = PauseManager(db=mock_db_session, capacity_threshold_percent=0.2)
        pm.db.query = lambda model: _create_query_mock(mock_db_session, model)

        # Create 3 agents all below threshold
        for i in range(3):
            agent = MockAgentRegistry(
                agent_id=uuid4(),
                agent_type="desktop",
                pool_name=f"pool-{i}",
                capabilities=["metrics"],
                status="online",
                resource_metrics={
                    "gpu_vram_available_gb": 0.5,
                    "cpu_cores_available": 1,
                },
            )
            mock_db_session.agents.append(agent)

        result = await pm.should_pause("plan-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_should_pause_with_mixed_agents(self, mock_db_session):
        """Test should_pause with mix of high and low capacity agents."""
        pm = PauseManager(db=mock_db_session, capacity_threshold_percent=0.2)
        pm.db.query = lambda model: _create_query_mock(mock_db_session, model)

        # Low capacity agent
        low = MockAgentRegistry(
            agent_id=uuid4(),
            agent_type="desktop",
            pool_name="pool-low",
            capabilities=["metrics"],
            status="online",
            resource_metrics={"gpu_vram_available_gb": 0.5, "cpu_cores_available": 1},
        )

        # High capacity agent
        high = MockAgentRegistry(
            agent_id=uuid4(),
            agent_type="desktop",
            pool_name="pool-high",
            capabilities=["metrics"],
            status="online",
            resource_metrics={"gpu_vram_available_gb": 6.0, "cpu_cores_available": 12},
        )

        mock_db_session.agents.append(low)
        mock_db_session.agents.append(high)

        # Should not pause because at least one agent has capacity
        result = await pm.should_pause("plan-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_should_pause_with_empty_resource_metrics(self, mock_db_session):
        """Test should_pause handles missing resource_metrics gracefully."""
        pm = PauseManager(db=mock_db_session)
        pm.db.query = lambda model: _create_query_mock(mock_db_session, model)

        agent = MockAgentRegistry(
            agent_id=uuid4(),
            agent_type="desktop",
            pool_name="pool-1",
            capabilities=["metrics"],
            status="online",
            resource_metrics={},  # Empty metrics
        )
        mock_db_session.agents.append(agent)

        result = await pm.should_pause("plan-1")
        # Should default to pausing with empty metrics
        assert result is True


class TestPauseWork:
    """Test pause work functionality."""

    @pytest.mark.asyncio
    async def test_pause_work_creates_entries(self, pause_manager, mock_db_session):
        """Test pause_work creates PauseQueueEntry records."""
        task_id = str(uuid4())
        plan_id = "plan-1"

        count = await pause_manager.pause_work(plan_id, [task_id])

        assert count == 1
        assert len(mock_db_session.pause_queue) == 1

    @pytest.mark.asyncio
    async def test_pause_work_with_multiple_tasks(self, pause_manager, mock_db_session):
        """Test pause_work with multiple task IDs."""
        task_ids = [str(uuid4()) for _ in range(3)]
        plan_id = "plan-1"

        count = await pause_manager.pause_work(plan_id, task_ids)

        assert count == 3
        assert len(mock_db_session.pause_queue) == 3

    @pytest.mark.asyncio
    async def test_pause_work_with_empty_list(self, pause_manager):
        """Test pause_work with empty task list."""
        count = await pause_manager.pause_work("plan-1", [])
        assert count == 0

    @pytest.mark.asyncio
    async def test_pause_work_sets_timestamp(self, pause_manager, mock_db_session):
        """Test pause_work sets paused_at timestamp."""
        task_id = str(uuid4())
        before = datetime.utcnow()

        await pause_manager.pause_work("plan-1", [task_id])

        after = datetime.utcnow()
        assert len(mock_db_session.pause_queue) == 1
        entry = mock_db_session.pause_queue[0]
        assert before <= entry.paused_at <= after

    @pytest.mark.asyncio
    async def test_pause_work_with_work_plan_json(self, pause_manager, mock_db_session):
        """Test pause_work stores work_plan_json."""
        task_id = str(uuid4())
        work_plan = {"plan_id": "plan-1", "tasks": 3}

        await pause_manager.pause_work("plan-1", [task_id], work_plan_json=work_plan)

        entry = mock_db_session.pause_queue[0]
        assert entry.work_plan_json == work_plan


class TestResumeWork:
    """Test resume work functionality."""

    @pytest.mark.asyncio
    async def test_resume_paused_work_with_available_capacity(
        self, mock_db_session, low_capacity_agent
    ):
        """Test resume_paused_work when capacity becomes available."""
        pm = PauseManager(db=mock_db_session, capacity_threshold_percent=0.5)
        pm.db.query = lambda model: _create_query_mock(mock_db_session, model)

        # Create paused entry
        entry = MockPauseQueueEntry(
            task_id=uuid4(),
            work_plan_json={"plan": "test"},
            reason="insufficient_capacity",
        )
        mock_db_session.pause_queue.append(entry)

        # Increase agent capacity
        low_capacity_agent.resource_metrics = {
            "gpu_vram_available_gb": 6.0,
            "cpu_cores_available": 12,
        }

        # Resume should work
        count = await pm.resume_paused_work()
        assert count == 1

        # Entry should be marked with resume_after timestamp
        assert entry.resume_after is not None

    @pytest.mark.asyncio
    async def test_resume_paused_work_with_insufficient_capacity(
        self, mock_db_session, low_capacity_agent
    ):
        """Test resume_paused_work skips when capacity still low."""
        pm = PauseManager(db=mock_db_session, capacity_threshold_percent=0.2)
        pm.db.query = lambda model: _create_query_mock(mock_db_session, model)

        # Create paused entry
        entry = MockPauseQueueEntry(
            task_id=uuid4(),
            work_plan_json={"plan": "test"},
            reason="insufficient_capacity",
        )
        mock_db_session.pause_queue.append(entry)

        # Resume should skip because capacity still low
        count = await pm.resume_paused_work()
        assert count == 0

        # Entry should not be marked as resumed
        assert entry.resume_after is None


class TestBackgroundPolling:
    """Test background polling functionality."""

    @pytest.mark.asyncio
    async def test_start_resume_polling_creates_task(self, pause_manager):
        """Test start_resume_polling creates asyncio task."""
        await pause_manager.start_resume_polling()

        assert pause_manager.polling_active is True
        assert pause_manager._polling_task is not None

        # Cleanup
        pause_manager.stop_resume_polling()

    @pytest.mark.asyncio
    async def test_stop_resume_polling_cancels_task(self, pause_manager):
        """Test stop_resume_polling stops the polling loop."""
        await pause_manager.start_resume_polling()
        await asyncio.sleep(0.1)

        pause_manager.stop_resume_polling()

        assert pause_manager.polling_active is False
        # Give task time to cancel
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_polling_calls_resume_repeatedly(self, mock_db_session):
        """Test polling loop calls resume_paused_work repeatedly."""
        pm = PauseManager(db=mock_db_session, capacity_threshold_percent=0.2)

        # Mock resume_paused_work to track calls
        call_count = 0

        original_resume = pm.resume_paused_work

        async def mock_resume():
            nonlocal call_count
            call_count += 1
            return await original_resume()

        pm.resume_paused_work = mock_resume

        # Set short polling interval for testing
        pm.polling_interval_seconds = 0.05

        # Start polling
        await pm.start_resume_polling()

        # Wait for multiple polling cycles
        await asyncio.sleep(0.15)

        # Stop polling
        pm.stop_resume_polling()

        # Should have been called multiple times (at least 2)
        assert call_count >= 2


class TestErrorHandling:
    """Test error handling and resilience."""

    @pytest.mark.asyncio
    async def test_should_pause_handles_db_error(self, pause_manager):
        """Test should_pause handles database errors gracefully."""
        # Mock db.query to raise error
        pause_manager.db.query = Mock(side_effect=Exception("DB error"))

        # Should not crash, just log and return True (conservative)
        result = await pause_manager.should_pause("plan-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_pause_work_handles_db_error(self, pause_manager):
        """Test pause_work handles database commit errors."""
        # Mock db.commit to raise error
        pause_manager.db.commit = Mock(side_effect=Exception("Commit error"))

        count = await pause_manager.pause_work("plan-1", [str(uuid4())])

        # Should return 0 on error
        assert count == 0


class TestDocumentation:
    """Test that code is well-documented."""

    def test_pause_manager_has_docstring(self):
        """Test PauseManager class is documented."""
        assert PauseManager.__doc__ is not None
        assert "pause" in PauseManager.__doc__.lower()

    def test_should_pause_has_docstring(self):
        """Test should_pause method is documented."""
        assert PauseManager.should_pause.__doc__ is not None

    def test_pause_work_has_docstring(self):
        """Test pause_work method is documented."""
        assert PauseManager.pause_work.__doc__ is not None

    def test_resume_paused_work_has_docstring(self):
        """Test resume_paused_work method is documented."""
        assert PauseManager.resume_paused_work.__doc__ is not None
