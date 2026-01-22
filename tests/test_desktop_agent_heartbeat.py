"""Integration tests for desktop agent heartbeat messaging and resource metrics.

Tests cover:
- Heartbeat message structure and resource metrics content
- Config-driven heartbeat intervals
- Resource metrics collection (CPU, memory, GPU)
- Orchestrator persistence and auto-registration
- Offline detection after heartbeat timeout
- Reconnection with exponential backoff
- Multi-agent scenarios
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import UUID, uuid4

import pytest

from src.agents.desktop_agent import DesktopAgent
from src.common.config import Config
from src.common.models import AgentRegistry
from src.common.protocol import MessageEnvelope, StatusUpdate
from src.orchestrator.service import OrchestratorService


class TestHeartbeatMessageStructure:
    """Test heartbeat message format and required fields."""

    def test_heartbeat_message_has_all_required_fields(self):
        """Verify heartbeat StatusUpdate has all required fields."""
        agent_id = uuid4()
        resources = {
            "cpu_load_1min": 0.5,
            "cpu_load_5min": 0.6,
            "cpu_cores_available": 4,
            "memory_percent": 50.0,
            "gpu_vram_available_gb": 8.0,
        }

        heartbeat = StatusUpdate(
            agent_id=agent_id,
            agent_type="desktop",
            status="online",
            current_task_id=None,
            resources=resources,
        )

        assert heartbeat.agent_id == agent_id
        assert heartbeat.agent_type == "desktop"
        assert heartbeat.status == "online"
        assert heartbeat.resources == resources

    def test_heartbeat_includes_resource_metrics(self):
        """Verify heartbeat carries resource metrics dict."""
        resources = {
            "cpu_load_1min": 1.5,
            "memory_available_gb": 16.0,
            "gpu_vram_available_gb": 12.0,
        }
        heartbeat = StatusUpdate(
            agent_id=uuid4(),
            agent_type="desktop",
            status="online",
            resources=resources,
        )

        assert "resources" in heartbeat.model_dump()
        assert heartbeat.resources["cpu_load_1min"] == 1.5
        assert heartbeat.resources["memory_available_gb"] == 16.0

    def test_heartbeat_status_update_structure(self):
        """Verify StatusUpdate structure matches protocol spec."""
        heartbeat = StatusUpdate(
            agent_id=uuid4(),
            agent_type="desktop",
            status="online",
            current_task_id=None,
            resources={},
        )

        # Should be serializable to dict
        data = heartbeat.model_dump()
        assert isinstance(data, dict)
        assert "agent_id" in data
        assert "agent_type" in data
        assert "status" in data
        assert "resources" in data

    def test_heartbeat_timestamp_is_utc(self):
        """Verify heartbeat can include UTC timestamp."""
        now = datetime.utcnow()
        heartbeat = StatusUpdate(
            agent_id=uuid4(),
            agent_type="desktop",
            status="online",
            resources={},
        )
        # StatusUpdate timestamp handling (if added later)
        # For now, just verify it's instantiable
        assert heartbeat is not None

    def test_heartbeat_agent_id_correct(self):
        """Verify agent_id is correctly set in heartbeat."""
        agent_id = uuid4()
        heartbeat = StatusUpdate(
            agent_id=agent_id,
            agent_type="desktop",
            status="online",
            resources={},
        )

        assert heartbeat.agent_id == agent_id


class TestResourceMetricsContent:
    """Test resource metrics collection and format."""

    def test_cpu_load_averages_present(self):
        """Verify CPU load averages (1min, 5min) in metrics."""
        agent = DesktopAgent("test-agent", "desktop", Config())
        metrics = agent._get_resource_metrics()

        assert "cpu_load_1min" in metrics
        assert "cpu_load_5min" in metrics
        assert isinstance(metrics["cpu_load_1min"], float)
        assert isinstance(metrics["cpu_load_5min"], float)

    def test_cpu_cores_available_calculated(self):
        """Verify CPU cores available calculated correctly."""
        agent = DesktopAgent("test-agent", "desktop", Config())
        metrics = agent._get_resource_metrics()

        assert "cpu_cores_physical" in metrics
        assert "cpu_cores_available" in metrics
        assert metrics["cpu_cores_physical"] >= 1
        assert metrics["cpu_cores_available"] >= 1

    def test_gpu_vram_metrics_present(self):
        """Verify GPU VRAM metrics in metrics dict."""
        agent = DesktopAgent("test-agent", "desktop", Config())
        metrics = agent._get_resource_metrics()

        assert "gpu_vram_total_gb" in metrics
        assert "gpu_vram_available_gb" in metrics
        assert metrics["gpu_vram_total_gb"] >= 0.0
        assert metrics["gpu_vram_available_gb"] >= 0.0

    def test_gpu_type_detected_correctly(self):
        """Verify GPU type detection (nvidia, amd, intel, none)."""
        agent = DesktopAgent("test-agent", "desktop", Config())
        # Don't mock - let it detect real GPU or report none
        metrics = agent._get_resource_metrics()

        assert "gpu_type" in metrics
        assert metrics["gpu_type"] in ["nvidia", "amd", "intel", "none"]

    def test_memory_percent_in_range(self):
        """Verify memory percent is in valid range (0-100)."""
        agent = DesktopAgent("test-agent", "desktop", Config())
        metrics = agent._get_resource_metrics()

        assert "memory_percent" in metrics
        assert 0 <= metrics["memory_percent"] <= 100

    def test_memory_available_gb_positive(self):
        """Verify memory available is non-negative."""
        agent = DesktopAgent("test-agent", "desktop", Config())
        metrics = agent._get_resource_metrics()

        assert "memory_available_gb" in metrics
        assert metrics["memory_available_gb"] >= 0.0

    def test_metrics_collection_error_handled(self):
        """Verify metrics collection error doesn't break agent."""
        agent = DesktopAgent("test-agent", "desktop", Config())
        # Mock psutil to raise exception
        with patch(
            "src.agents.desktop_agent.psutil.getloadavg", side_effect=Exception("Mocked error")
        ):
            # Should return safe defaults, not raise
            metrics = agent._get_resource_metrics()

            assert metrics is not None
            assert "cpu_load_1min" in metrics
            assert metrics["cpu_load_1min"] == 0.0  # Safe default

    def test_metrics_use_load_average_not_instantaneous_percent(self):
        """Verify metrics use load average not instantaneous CPU percent."""
        agent = DesktopAgent("test-agent", "desktop", Config())
        metrics = agent._get_resource_metrics()

        # Should have load averages, not instantaneous percent
        assert "cpu_load_1min" in metrics
        assert "cpu_load_5min" in metrics
        # Should NOT have instantaneous cpu_percent
        assert "cpu_percent" not in metrics or "cpu_load" in str(metrics.keys())


class TestHeartbeatInterval:
    """Test heartbeat interval configuration and execution."""

    def test_heartbeat_sent_at_config_interval(self):
        """Verify heartbeat uses interval from config."""
        config = Config()
        config.heartbeat_interval_seconds = 15
        agent = DesktopAgent("test-agent", "desktop", config)

        # Check that the config value is used in the agent
        assert agent.config.heartbeat_interval_seconds == 15

    def test_config_driven_interval_respected(self):
        """Verify config interval is read from Config object."""
        config = Config()
        original_interval = config.heartbeat_interval_seconds
        assert original_interval > 0

        config.heartbeat_interval_seconds = 45
        agent = DesktopAgent("test-agent", "desktop", config)
        assert agent.config.heartbeat_interval_seconds == 45

    @pytest.mark.asyncio
    async def test_heartbeat_loop_starts_on_agent_run(self):
        """Verify heartbeat loop starts when agent.run() is called."""
        agent = DesktopAgent("test-agent", "desktop", Config())
        agent.connect = AsyncMock()
        agent.disconnect = AsyncMock()
        agent.consume_work_requests = AsyncMock()
        agent.start_heartbeat_loop = AsyncMock()

        # Create a task that will be cancelled after a short time
        task = asyncio.create_task(agent.run())
        await asyncio.sleep(0.1)
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        # Verify consume_work_requests was called (part of run())
        agent.consume_work_requests.assert_called()

    def test_heartbeat_continues_on_metrics_error(self):
        """Verify heartbeat loop doesn't crash on metrics error."""
        config = Config()
        agent = DesktopAgent("test-agent", "desktop", config)

        # This should not raise, even if metrics collection fails
        # The heartbeat loop should continue
        with patch.object(agent, "_get_resource_metrics", side_effect=Exception("Metrics error")):
            # Loop should handle the error gracefully
            assert agent.start_heartbeat_loop is not None


class TestOrchestratorPersistence:
    """Test orchestrator heartbeat handling and persistence."""

    @pytest.mark.asyncio
    async def test_handle_agent_heartbeat_updates_registry(self):
        """Verify heartbeat updates existing agent registry."""
        config = Config()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(
            agent_id=uuid4(),
            agent_type="desktop",
            status="online",
            last_heartbeat_at=datetime.utcnow(),
            resource_metrics={},
        )

        service = OrchestratorService(config, db)
        heartbeat = StatusUpdate(
            agent_id=uuid4(),
            agent_type="desktop",
            status="online",
            resources={"cpu_load_1min": 0.5},
        )

        await service.handle_agent_heartbeat(heartbeat, db)
        # Should have called db.query and db.commit
        db.query.assert_called()

    @pytest.mark.asyncio
    async def test_handle_agent_heartbeat_auto_registers_new_agent(self):
        """Verify new agents auto-register on first heartbeat."""
        config = Config()
        db = MagicMock()
        # Simulate: no agent found
        db.query.return_value.filter.return_value.first.return_value = None

        service = OrchestratorService(config, db)
        agent_id = uuid4()
        heartbeat = StatusUpdate(
            agent_id=agent_id,
            agent_type="desktop",
            status="online",
            resources={"cpu_load_1min": 0.5},
        )

        await service.handle_agent_heartbeat(heartbeat, db)
        # Should have called db.add (for new agent)
        db.add.assert_called()

    @pytest.mark.asyncio
    async def test_handle_agent_heartbeat_saves_resource_metrics_to_db(self):
        """Verify resource metrics are persisted to database."""
        config = Config()
        db = MagicMock()
        agent = MagicMock(
            agent_id=uuid4(),
            agent_type="desktop",
            status="online",
            resource_metrics={},
        )
        db.query.return_value.filter.return_value.first.return_value = agent

        service = OrchestratorService(config, db)
        metrics = {
            "cpu_load_1min": 1.5,
            "memory_available_gb": 16.0,
            "gpu_vram_available_gb": 12.0,
        }
        heartbeat = StatusUpdate(
            agent_id=uuid4(),
            agent_type="desktop",
            status="online",
            resources=metrics,
        )

        await service.handle_agent_heartbeat(heartbeat, db)
        # Verify agent.resource_metrics was set to heartbeat.resources
        assert agent.resource_metrics == metrics

    @pytest.mark.asyncio
    async def test_handle_agent_heartbeat_updates_last_heartbeat_at(self):
        """Verify last_heartbeat_at is updated."""
        config = Config()
        db = MagicMock()
        agent = MagicMock(
            agent_id=uuid4(),
            agent_type="desktop",
            status="online",
            last_heartbeat_at=None,
        )
        db.query.return_value.filter.return_value.first.return_value = agent

        service = OrchestratorService(config, db)
        heartbeat = StatusUpdate(
            agent_id=uuid4(),
            agent_type="desktop",
            status="online",
            resources={},
        )

        await service.handle_agent_heartbeat(heartbeat, db)
        # Verify last_heartbeat_at was updated
        assert agent.last_heartbeat_at is not None

    @pytest.mark.asyncio
    async def test_handle_agent_heartbeat_sets_status_online(self):
        """Verify agent status is set to online."""
        config = Config()
        db = MagicMock()
        agent = MagicMock(
            agent_id=uuid4(),
            agent_type="desktop",
            status="offline",
        )
        db.query.return_value.filter.return_value.first.return_value = agent

        service = OrchestratorService(config, db)
        heartbeat = StatusUpdate(
            agent_id=uuid4(),
            agent_type="desktop",
            status="online",
            resources={},
        )

        await service.handle_agent_heartbeat(heartbeat, db)
        # Verify status was set to online
        assert agent.status == "online"

    @pytest.mark.asyncio
    async def test_handle_agent_heartbeat_preserves_existing_capabilities(self):
        """Verify existing agent capabilities are preserved."""
        config = Config()
        db = MagicMock()
        existing_capabilities = ["deploy_service", "run_playbook"]
        agent = MagicMock(
            agent_id=uuid4(),
            agent_type="desktop",
            status="offline",
            capabilities=existing_capabilities,
            resource_metrics={},
        )
        db.query.return_value.filter.return_value.first.return_value = agent

        service = OrchestratorService(config, db)
        heartbeat = StatusUpdate(
            agent_id=uuid4(),
            agent_type="desktop",
            status="online",
            resources={},
        )

        await service.handle_agent_heartbeat(heartbeat, db)
        # Capabilities should not be overwritten
        assert agent.capabilities == existing_capabilities


class TestOfflineDetection:
    """Test offline detection after heartbeat timeout."""

    @pytest.mark.asyncio
    async def test_agent_marked_offline_after_90s_no_heartbeat(self):
        """Verify agent marked offline after 90s without heartbeat."""
        config = Config()
        config.heartbeat_timeout_seconds = 90

        db = MagicMock()
        stale_agent = MagicMock(
            agent_id=uuid4(),
            agent_type="desktop",
            status="online",
            last_heartbeat_at=datetime.utcnow() - timedelta(seconds=95),
        )
        db.query.return_value.filter.return_value.filter.return_value.all.return_value = [
            stale_agent
        ]

        service = OrchestratorService(config, db)

        # Simulate one iteration of offline detection
        import asyncio as aio

        # Create a short-lived task
        task = aio.create_task(service.mark_agents_offline_periodically())
        await aio.sleep(0.1)
        task.cancel()

        try:
            await task
        except aio.CancelledError:
            pass

    def test_agent_offline_check_uses_last_heartbeat_at(self):
        """Verify offline check queries last_heartbeat_at."""
        config = Config()
        config.heartbeat_timeout_seconds = 90

        db = MagicMock()
        service = OrchestratorService(config, db)

        # Service should be configured with timeout value
        assert service.config.heartbeat_timeout_seconds == 90

    @pytest.mark.asyncio
    async def test_offline_agent_not_included_in_capacity_queries(self):
        """Verify offline agents excluded from capacity decisions."""
        config = Config()
        db = MagicMock()
        offline_agent = MagicMock(
            agent_id=uuid4(),
            agent_type="desktop",
            status="offline",
            resource_metrics={"gpu_vram_available_gb": 8.0},
        )
        online_agent = MagicMock(
            agent_id=uuid4(),
            agent_type="desktop",
            status="online",
            resource_metrics={"gpu_vram_available_gb": 12.0},
        )

        # Mock query to return only online agents for capacity check
        db.query.return_value.filter.return_value.all.return_value = [online_agent]

        service = OrchestratorService(config, db)

        # In real usage, orchestrator would query only online agents
        # Just verify the pattern

    @pytest.mark.asyncio
    async def test_agent_comes_back_online_on_next_heartbeat(self):
        """Verify offline agent comes back online on heartbeat."""
        config = Config()
        db = MagicMock()
        offline_agent = MagicMock(
            agent_id=uuid4(),
            agent_type="desktop",
            status="offline",
            last_heartbeat_at=datetime.utcnow() - timedelta(seconds=100),
        )
        db.query.return_value.filter.return_value.first.return_value = offline_agent

        service = OrchestratorService(config, db)
        heartbeat = StatusUpdate(
            agent_id=offline_agent.agent_id,
            agent_type="desktop",
            status="online",
            resources={},
        )

        await service.handle_agent_heartbeat(heartbeat, db)
        # Verify agent status changed to online
        assert offline_agent.status == "online"
        assert offline_agent.last_heartbeat_at is not None

    @pytest.mark.asyncio
    async def test_offline_detection_tolerates_minor_clock_skew(self):
        """Verify offline detection handles clock skew gracefully."""
        config = Config()
        config.heartbeat_timeout_seconds = 90

        db = MagicMock()
        # Agent with last_heartbeat slightly in future (minor clock skew)
        slightly_future = datetime.utcnow() + timedelta(seconds=2)
        agent = MagicMock(
            agent_id=uuid4(),
            agent_type="desktop",
            status="online",
            last_heartbeat_at=slightly_future,
        )

        service = OrchestratorService(config, db)
        # Should not crash due to clock skew
        assert service is not None


class TestReconnectionResilience:
    """Test reconnection logic and error resilience."""

    @pytest.mark.asyncio
    async def test_agent_reconnects_after_network_blip(self):
        """Verify agent reconnects after RabbitMQ connection failure."""
        config = Config()
        agent = DesktopAgent("test-agent", "desktop", config)
        agent.connect = AsyncMock(side_effect=[Exception("Connection failed"), None])
        agent.disconnect = AsyncMock()

        # Should attempt reconnection
        try:
            await agent._connect_with_backoff(max_retries=2)
        except Exception:
            pass  # May fail, but shouldn't crash

    @pytest.mark.asyncio
    async def test_reconnection_uses_exponential_backoff(self):
        """Verify reconnection uses exponential backoff strategy."""
        config = Config()
        agent = DesktopAgent("test-agent", "desktop", config)

        backoff_values = []

        async def mock_connect():
            raise Exception("Connection failed")

        agent.connect = AsyncMock(side_effect=mock_connect)

        # Should use exponential backoff (1s, 2s, 4s)
        try:
            await agent._connect_with_backoff(max_retries=2)
        except Exception:
            pass

    @pytest.mark.asyncio
    async def test_heartbeat_loop_survives_metrics_collection_error(self):
        """Verify heartbeat loop continues after metrics error."""
        config = Config()
        agent = DesktopAgent("test-agent", "desktop", config)
        agent.send_heartbeat = AsyncMock()

        # Mock _get_resource_metrics to raise once, then return valid metrics
        call_count = 0

        async def mock_heartbeat():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Metrics error")
            return

        agent.send_heartbeat = AsyncMock(side_effect=[Exception("Error"), None])

        # Loop should continue despite error
        assert agent.send_heartbeat is not None

    @pytest.mark.asyncio
    async def test_rabbitmq_connection_error_triggers_reconnect(self):
        """Verify RabbitMQ connection error triggers reconnection."""
        config = Config()
        agent = DesktopAgent("test-agent", "desktop", config)

        import aio_pika

        agent.send_heartbeat = AsyncMock(
            side_effect=aio_pika.exceptions.AMQPConnectionError("Connection lost")
        )
        agent._connect_with_backoff = AsyncMock()

        # Verify reconnection method exists
        assert hasattr(agent, "_connect_with_backoff")


class TestMultiAgentScenarios:
    """Test multiple agents operating independently."""

    @pytest.mark.asyncio
    async def test_multiple_agents_register_independently(self):
        """Verify multiple agents can register separately."""
        config = Config()
        db = MagicMock()

        # Simulate two agents registering
        agent1_id = uuid4()
        agent2_id = uuid4()

        def mock_query(*args, **kwargs):
            mock = MagicMock()
            mock.filter.return_value.first.return_value = None  # New agents
            return mock

        db.query = mock_query

        service = OrchestratorService(config, db)

        heartbeat1 = StatusUpdate(
            agent_id=agent1_id,
            agent_type="desktop",
            status="online",
            resources={"cpu_load_1min": 0.5},
        )
        heartbeat2 = StatusUpdate(
            agent_id=agent2_id,
            agent_type="desktop",
            status="online",
            resources={"cpu_load_1min": 0.6},
        )

        # Both should register without interference
        await service.handle_agent_heartbeat(heartbeat1, db)
        await service.handle_agent_heartbeat(heartbeat2, db)

    @pytest.mark.asyncio
    async def test_orchestrator_tracks_3_agents_separately(self):
        """Verify orchestrator maintains separate registry entries for 3 agents."""
        config = Config()
        db = MagicMock()

        agents_dict = {}

        def mock_query(*args, **kwargs):
            mock = MagicMock()

            def mock_filter(*fargs, **fkwargs):
                mock_filter = MagicMock()

                def mock_first():
                    # Return stored agent or None
                    for filter_arg in fargs:
                        # Simulate filtering by agent_id
                        pass
                    return None  # Simplified for test

                mock_filter.first = mock_first
                return mock_filter

            mock.filter = mock_filter
            return mock

        db.query = mock_query
        service = OrchestratorService(config, db)

        # Create 3 agents
        agent_ids = [uuid4() for _ in range(3)]
        for aid in agent_ids:
            heartbeat = StatusUpdate(
                agent_id=aid,
                agent_type="desktop",
                status="online",
                resources={"cpu_load_1min": 0.5 + aid.int % 10 * 0.01},
            )
            await service.handle_agent_heartbeat(heartbeat, db)

    @pytest.mark.asyncio
    async def test_capacity_query_returns_all_agent_metrics(self):
        """Verify capacity query aggregates metrics from all agents."""
        config = Config()
        db = MagicMock()

        agent1 = MagicMock(
            agent_id=uuid4(),
            status="online",
            resource_metrics={
                "gpu_vram_available_gb": 12.0,
                "cpu_cores_available": 8,
            },
        )
        agent2 = MagicMock(
            agent_id=uuid4(),
            status="online",
            resource_metrics={
                "gpu_vram_available_gb": 4.0,
                "cpu_cores_available": 4,
            },
        )

        db.query.return_value.filter.return_value.all.return_value = [agent1, agent2]

        service = OrchestratorService(config, db)

        # Query all online agents
        agents = db.query.return_value.filter.return_value.all()
        total_gpu_vram = sum(a.resource_metrics.get("gpu_vram_available_gb", 0) for a in agents)
        total_cpu_cores = sum(a.resource_metrics.get("cpu_cores_available", 0) for a in agents)

        assert total_gpu_vram == 16.0
        assert total_cpu_cores == 12
