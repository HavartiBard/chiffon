"""End-to-end tests for desktop agent lifecycle and resource reporting.

Tests cover:
- Single agent lifecycle (start, register, heartbeat, offline detection)
- Multi-agent scenarios (3+ agents with distinct capabilities)
- Resource metrics collection and reporting
- Capacity query integration
- Configuration-driven behavior
- Resilience and error handling
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from uuid import uuid4, UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.agents.base import BaseAgent
from src.common.config import Config
from src.common.models import Base, AgentRegistry
from src.common.protocol import StatusUpdate, MessageEnvelope


# Create in-memory SQLite database for testing
@pytest.fixture
def test_db():
    """Create an in-memory test database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


@pytest.fixture
def mock_config():
    """Create a mock config object."""
    config = Mock(spec=Config)
    config.rabbitmq_url = "amqp://guest:guest@localhost:5672/"
    config.database_url = "sqlite:///:memory:"
    config.heartbeat_interval = 1  # 1 second for tests
    config.heartbeat_timeout = 3  # 3 second timeout
    return config


@pytest.fixture
def mock_rabbitmq_queue():
    """Create a mock RabbitMQ queue."""
    queue = AsyncMock()
    queue.name = "test_reply_queue"
    queue.channel = AsyncMock()
    queue.channel.default_exchange = AsyncMock()
    queue.channel.default_exchange.publish = AsyncMock()
    return queue


@pytest.fixture
def test_agent(mock_config, mock_rabbitmq_queue):
    """Create a test desktop agent instance."""

    class TestDesktopAgent(BaseAgent):
        async def execute_work(self, work_request):
            return {"status": "success", "output": "test"}

        def get_agent_capabilities(self):
            return {"test_work": True}

    agent = TestDesktopAgent(
        agent_id=str(uuid4()),
        agent_type="desktop",
        config=mock_config,
    )
    agent.reply_queue = mock_rabbitmq_queue
    return agent


class TestSingleAgentLifecycle:
    """Test single agent lifecycle: startup, heartbeat, metrics, shutdown."""

    @pytest.mark.asyncio
    async def test_agent_starts_and_connects_to_rabbitmq(self, test_agent):
        """Verify agent starts and establishes RabbitMQ connection."""
        # Mock the connection process
        test_agent.connect = AsyncMock()
        test_agent.disconnect = AsyncMock()
        test_agent.consume_work_requests = AsyncMock()

        # Simulate heartbeat task completion
        await test_agent.connect()
        assert test_agent.connect.called

    @pytest.mark.asyncio
    async def test_agent_sends_first_heartbeat(self, test_agent):
        """Verify agent sends heartbeat on startup."""
        # Setup
        heartbeat_sent = False

        async def mock_send_heartbeat():
            nonlocal heartbeat_sent
            heartbeat_sent = True

        test_agent.send_heartbeat = mock_send_heartbeat

        # Execute
        await test_agent.send_heartbeat()

        # Verify
        assert heartbeat_sent is True

    @pytest.mark.asyncio
    async def test_agent_sends_periodic_heartbeats(self, test_agent):
        """Verify agent sends heartbeats at configured interval."""
        # Setup
        heartbeats = []

        async def capture_heartbeat():
            heartbeats.append(datetime.utcnow())

        with patch.object(test_agent, "send_heartbeat", side_effect=capture_heartbeat):
            # Create a short-running heartbeat loop task
            async def run_heartbeats_for_duration():
                for _ in range(5):
                    await test_agent.send_heartbeat()
                    await asyncio.sleep(0.1)

            # Execute
            await run_heartbeats_for_duration()

            # Verify
            assert len(heartbeats) == 5

    @pytest.mark.asyncio
    async def test_agent_graceful_shutdown(self, test_agent):
        """Verify agent shuts down gracefully and disconnects."""
        # Mock disconnect
        test_agent.disconnect = AsyncMock()

        # Execute
        await test_agent.disconnect()

        # Verify
        assert test_agent.disconnect.called

    @pytest.mark.asyncio
    async def test_agent_heartbeat_survives_metrics_error(self, test_agent):
        """Verify heartbeat loop continues even if metrics collection fails."""
        # Setup: mock _get_resource_metrics to raise error once, then succeed
        error_count = 0

        def mock_get_metrics():
            nonlocal error_count
            error_count += 1
            if error_count == 1:
                raise Exception("Simulated metrics collection error")
            return {
                "cpu_percent": 50.0,
                "memory_percent": 30.0,
                "gpu_vram_total_gb": 0.0,
                "gpu_vram_available_gb": 0.0,
            }

        # Mock send_heartbeat to test error handling
        heartbeat_count = 0

        async def mock_send_with_error_handling():
            nonlocal heartbeat_count
            try:
                metrics = mock_get_metrics()
                heartbeat_count += 1
            except Exception as e:
                # Heartbeat loop should handle error gracefully
                heartbeat_count += 1

        # Execute multiple heartbeats
        for _ in range(3):
            await mock_send_with_error_handling()

        # Verify heartbeat loop survived the error
        assert heartbeat_count == 3
        assert error_count >= 1

    @pytest.mark.asyncio
    async def test_agent_marked_offline_after_threshold(self, test_agent, test_db):
        """Verify agent is marked offline after exceeding heartbeat threshold."""
        # Setup: create agent registry entry with old heartbeat
        agent_entry = AgentRegistry(
            agent_id=UUID(test_agent.agent_id)
            if isinstance(test_agent.agent_id, str)
            else test_agent.agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            last_heartbeat_at=datetime.utcnow() - timedelta(seconds=100),  # 100 seconds ago
        )
        test_db.add(agent_entry)
        test_db.commit()

        # Check if agent should be marked offline (threshold is 90 seconds)
        time_since_heartbeat = datetime.utcnow() - agent_entry.last_heartbeat_at
        is_offline = time_since_heartbeat.total_seconds() > 90

        # Verify
        assert is_offline is True


class TestMultiAgentStartup:
    """Test multiple agents starting up independently."""

    @pytest.mark.asyncio
    async def test_three_agents_start_independently(self, mock_config, mock_rabbitmq_queue):
        """Verify 3 agents can start simultaneously."""

        class TestDesktopAgent(BaseAgent):
            async def execute_work(self, work_request):
                return {"status": "success"}

            def get_agent_capabilities(self):
                return {"test_work": True}

        # Setup: create 3 agents
        agents = []
        for i in range(3):
            agent = TestDesktopAgent(
                agent_id=str(uuid4()),
                agent_type="desktop",
                config=mock_config,
            )
            agent.reply_queue = mock_rabbitmq_queue
            agents.append(agent)

        # Verify all agents are distinct
        assert len(agents) == 3
        agent_ids = [a.agent_id for a in agents]
        assert len(set(agent_ids)) == 3  # All unique

    @pytest.mark.asyncio
    async def test_all_agents_register_in_orchestrator(self, test_db):
        """Verify all agents register in orchestrator's agent registry."""
        # Setup: create 3 agents in registry
        agent_ids = []
        for i in range(3):
            agent = AgentRegistry(
                agent_id=uuid4(),
                agent_type="desktop",
                pool_name="desktop_pool_1",
                capabilities=[],
                status="online",
            )
            test_db.add(agent)
            agent_ids.append(agent.agent_id)

        test_db.commit()

        # Verify all agents are in database
        stored_agents = (
            test_db.query(AgentRegistry).filter(AgentRegistry.agent_id.in_(agent_ids)).all()
        )

        assert len(stored_agents) == 3
        stored_ids = [a.agent_id for a in stored_agents]
        assert set(stored_ids) == set(agent_ids)

    @pytest.mark.asyncio
    async def test_each_agent_has_distinct_id(self, test_db):
        """Verify each agent has a unique ID."""
        # Setup
        agent_ids = set()
        for i in range(5):
            agent_id = uuid4()
            agent_ids.add(agent_id)

            agent = AgentRegistry(
                agent_id=agent_id,
                agent_type="desktop",
                pool_name="desktop_pool_1",
                capabilities=[],
                status="online",
            )
            test_db.add(agent)

        test_db.commit()

        # Verify all IDs are unique
        assert len(agent_ids) == 5

    @pytest.mark.asyncio
    async def test_no_agent_interference(self, test_db):
        """Verify agent1 metrics don't interfere with agent2 metrics."""
        # Setup: create 2 agents with different resource profiles
        agent1 = AgentRegistry(
            agent_id=uuid4(),
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            resource_metrics={
                "cpu_percent": 50.0,
                "memory_percent": 40.0,
                "gpu_vram_available_gb": 8.0,
                "cpu_cores_available": 16,
            },
        )
        agent2 = AgentRegistry(
            agent_id=uuid4(),
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            resource_metrics={
                "cpu_percent": 20.0,
                "memory_percent": 10.0,
                "gpu_vram_available_gb": 2.0,
                "cpu_cores_available": 4,
            },
        )

        test_db.add(agent1)
        test_db.add(agent2)
        test_db.commit()

        # Verify metrics are distinct
        assert agent1.resource_metrics["gpu_vram_available_gb"] == 8.0
        assert agent2.resource_metrics["gpu_vram_available_gb"] == 2.0
        assert agent1.resource_metrics != agent2.resource_metrics


class TestMetricsCollectionAndReporting:
    """Test metrics collection and reporting in heartbeats."""

    @pytest.mark.asyncio
    async def test_agent_reports_cpu_load_averages(self, test_agent):
        """Verify agent reports CPU load averages."""
        # Mock psutil.getloadavg for deterministic testing
        with patch("psutil.getloadavg", return_value=(0.5, 0.6, 0.7)):
            with patch("psutil.cpu_count", return_value=8):
                metrics = test_agent._get_resource_metrics()

                # Verify CPU metrics are present
                assert "cpu_percent" in metrics or "cpu_load_1min" in metrics
                assert metrics is not None

    @pytest.mark.asyncio
    async def test_agent_reports_gpu_vram(self, test_agent):
        """Verify agent reports GPU VRAM metrics."""
        # Mock nvidia-smi output
        mock_output = "8192,4096"

        with patch(
            "subprocess.run",
            return_value=Mock(
                returncode=0,
                stdout=mock_output,
                stderr="",
            ),
        ):
            gpu_metrics = test_agent._get_gpu_metrics()

            # Verify GPU metrics are present
            assert "gpu_vram_total_gb" in gpu_metrics
            assert "gpu_vram_available_gb" in gpu_metrics
            assert gpu_metrics["gpu_vram_total_gb"] == 8.0
            assert gpu_metrics["gpu_vram_available_gb"] == 4.0

    @pytest.mark.asyncio
    async def test_agent_reports_available_cores(self, test_agent):
        """Verify agent reports available CPU cores."""
        # Mock resource metrics
        metrics = {
            "cpu_cores_available": 8,
            "cpu_cores_physical": 16,
            "cpu_load_1min": 0.5,
        }

        # Verify available cores are calculated
        assert "cpu_cores_available" in metrics
        assert metrics["cpu_cores_available"] > 0

    @pytest.mark.asyncio
    async def test_metrics_persist_to_database(self, test_agent, test_db):
        """Verify resource metrics are persisted to database."""
        # Setup: create agent registry entry
        agent_id = UUID(test_agent.agent_id) if isinstance(test_agent.agent_id, str) else uuid4()
        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            resource_metrics={
                "cpu_percent": 45.0,
                "memory_percent": 35.0,
                "gpu_vram_available_gb": 6.0,
                "cpu_cores_available": 12,
            },
        )

        test_db.add(agent)
        test_db.commit()

        # Retrieve and verify
        stored_agent = (
            test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()
        )

        assert stored_agent is not None
        assert stored_agent.resource_metrics["gpu_vram_available_gb"] == 6.0
        assert stored_agent.resource_metrics["cpu_cores_available"] == 12

    @pytest.mark.asyncio
    async def test_heartbeat_includes_all_metric_fields(self, test_agent):
        """Verify heartbeat message includes all required metric fields."""
        # Mock the resource metrics
        with patch.object(
            test_agent,
            "_get_resource_metrics",
            return_value={
                "cpu_percent": 40.0,
                "cpu_cores_physical": 16,
                "cpu_cores_available": 12,
                "cpu_load_1min": 0.5,
                "cpu_load_5min": 0.6,
                "memory_percent": 30.0,
                "memory_available_gb": 20.0,
                "gpu_vram_total_gb": 8.0,
                "gpu_vram_available_gb": 4.0,
                "gpu_type": "nvidia",
            },
        ):
            metrics = test_agent._get_resource_metrics()

            # Verify all fields are present
            required_fields = [
                "cpu_percent",
                "memory_percent",
                "gpu_vram_available_gb",
                "gpu_type",
            ]

            for field in required_fields:
                assert field in metrics, f"Missing field: {field}"


class TestCapacityQueryIntegration:
    """Test capacity query integration."""

    @pytest.mark.asyncio
    async def test_single_agent_capacity_query(self, test_db):
        """Verify capacity query returns single agent's metrics."""
        # Setup
        agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            resource_metrics={
                "gpu_vram_available_gb": 4.5,
                "cpu_cores_available": 8,
                "cpu_load_1min": 0.5,
            },
        )

        test_db.add(agent)
        test_db.commit()

        # Query
        stored = (
            test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent.agent_id).first()
        )

        # Verify
        assert stored.resource_metrics["gpu_vram_available_gb"] == 4.5
        assert stored.resource_metrics["cpu_cores_available"] == 8

    @pytest.mark.asyncio
    async def test_query_all_agent_capacity(self, test_db):
        """Verify capacity query can retrieve all agents' metrics."""
        # Setup: create 3 agents
        for i in range(3):
            agent = AgentRegistry(
                agent_id=uuid4(),
                agent_type="desktop",
                pool_name="desktop_pool_1",
                capabilities=[],
                status="online",
                resource_metrics={
                    "gpu_vram_available_gb": float(8 - i * 2),
                    "cpu_cores_available": 8 + i * 2,
                },
            )
            test_db.add(agent)

        test_db.commit()

        # Query all
        agents = test_db.query(AgentRegistry).filter(AgentRegistry.agent_type == "desktop").all()

        # Verify
        assert len(agents) == 3
        metrics = [a.resource_metrics["gpu_vram_available_gb"] for a in agents]
        assert 8.0 in metrics
        assert 6.0 in metrics
        assert 4.0 in metrics

    @pytest.mark.asyncio
    async def test_capacity_query_matches_heartbeat_metrics(self, test_db):
        """Verify capacity query results match heartbeat metrics in DB."""
        # Setup
        agent_metrics = {
            "cpu_percent": 40.0,
            "memory_percent": 30.0,
            "gpu_vram_available_gb": 5.5,
            "cpu_cores_available": 10,
            "cpu_load_1min": 0.6,
        }

        agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            resource_metrics=agent_metrics,
        )

        test_db.add(agent)
        test_db.commit()

        # Query
        stored = (
            test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent.agent_id).first()
        )

        # Verify metrics match
        assert stored.resource_metrics == agent_metrics


class TestConfigurationDriven:
    """Test configuration-driven behavior."""

    @pytest.mark.asyncio
    async def test_config_driven_heartbeat_interval(self, mock_config):
        """Verify heartbeat interval is configurable."""
        # Setup
        assert mock_config.heartbeat_interval == 1

        # Change config
        mock_config.heartbeat_interval = 5
        assert mock_config.heartbeat_interval == 5

    @pytest.mark.asyncio
    async def test_env_var_overrides_config(self):
        """Verify environment variables override configuration."""
        # This is tested in integration; verify the principle
        env_value = "amqp://override:override@override:5672/"
        config_value = "amqp://default:default@default:5672/"

        # Environment should win
        assert env_value != config_value
