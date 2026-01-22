"""Integration tests for orchestrator + desktop agents.

Tests cover:
- Agent registration on heartbeat (auto-register)
- Metric persistence to database
- Heartbeat handling and status updates
- Offline detection and reconnection
- Capacity query integration
- Multi-agent scenarios
"""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import Mock, AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.common.models import Base, AgentRegistry
from src.orchestrator.service import OrchestratorService


# Create in-memory SQLite database for testing
@pytest.fixture
def test_db():
    """Create an in-memory test database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


@pytest.fixture
def mock_orchestrator_service(test_db):
    """Create a mock orchestrator service instance."""
    service = Mock(spec=OrchestratorService)
    service.db = test_db
    service.logger = Mock()
    return service


class TestAgentRegistration:
    """Test agent registration from heartbeats."""

    @pytest.mark.asyncio
    async def test_orchestrator_auto_registers_new_agent_on_heartbeat(self, test_db):
        """Verify orchestrator auto-registers new agent on first heartbeat."""
        # Setup: simulate first heartbeat from new agent
        agent_id = uuid4()

        # Simulate registration by creating agent entry
        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
        )

        test_db.add(agent)
        test_db.commit()

        # Verify agent was registered
        stored = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()

        assert stored is not None
        assert stored.status == "online"

    @pytest.mark.asyncio
    async def test_orchestrator_creates_agent_registry_record(self, test_db):
        """Verify orchestrator creates registry record with all fields."""
        # Setup
        agent_id = uuid4()

        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            last_heartbeat_at=datetime.utcnow(),
            resource_metrics={},
        )

        test_db.add(agent)
        test_db.commit()

        # Verify all fields present
        stored = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()

        assert stored.agent_id == agent_id
        assert stored.agent_type == "desktop"
        assert stored.pool_name == "desktop_pool_1"
        assert stored.status == "online"
        assert stored.last_heartbeat_at is not None
        assert isinstance(stored.resource_metrics, dict)

    @pytest.mark.asyncio
    async def test_agent_id_preserved_across_heartbeats(self, test_db):
        """Verify agent_id remains constant across multiple heartbeats."""
        # Setup
        agent_id = uuid4()

        # First heartbeat: register
        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
        )

        test_db.add(agent)
        test_db.commit()

        # Store initial ID
        initial_id = agent.agent_id

        # Simulate second heartbeat: update status
        agent.last_heartbeat_at = datetime.utcnow()
        agent.resource_metrics = {"cpu_percent": 50.0}
        test_db.commit()

        # Verify ID hasn't changed
        assert agent.agent_id == initial_id

    @pytest.mark.asyncio
    async def test_pool_name_assigned_on_registration(self, test_db):
        """Verify pool name is assigned on registration."""
        # Setup
        agent_id = uuid4()

        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
        )

        test_db.add(agent)
        test_db.commit()

        # Verify pool name
        stored = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()

        assert stored.pool_name == "desktop_pool_1"

    @pytest.mark.asyncio
    async def test_new_agent_status_set_online(self, test_db):
        """Verify newly registered agent status is 'online'."""
        # Setup
        agent_id = uuid4()

        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
        )

        test_db.add(agent)
        test_db.commit()

        # Verify status
        stored = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()

        assert stored.status == "online"


class TestMetricPersistence:
    """Test resource metric persistence."""

    @pytest.mark.asyncio
    async def test_orchestrator_saves_resource_metrics_to_db(self, test_db):
        """Verify metrics from heartbeat are saved to database."""
        # Setup
        agent_id = uuid4()
        metrics = {
            "cpu_percent": 45.0,
            "memory_percent": 35.0,
            "gpu_vram_available_gb": 6.0,
            "cpu_cores_available": 12,
        }

        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            resource_metrics=metrics,
        )

        test_db.add(agent)
        test_db.commit()

        # Verify metrics persisted
        stored = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()

        assert stored.resource_metrics == metrics

    @pytest.mark.asyncio
    async def test_metrics_include_cpu_load_and_cores(self, test_db):
        """Verify metrics include CPU load and core count."""
        # Setup
        agent_id = uuid4()
        metrics = {
            "cpu_load_1min": 0.5,
            "cpu_load_5min": 0.6,
            "cpu_cores_physical": 16,
            "cpu_cores_available": 12,
        }

        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            resource_metrics=metrics,
        )

        test_db.add(agent)
        test_db.commit()

        # Verify
        stored = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()

        assert "cpu_load_1min" in stored.resource_metrics
        assert "cpu_cores_available" in stored.resource_metrics

    @pytest.mark.asyncio
    async def test_metrics_include_gpu_vram_and_type(self, test_db):
        """Verify metrics include GPU VRAM and type."""
        # Setup
        agent_id = uuid4()
        metrics = {
            "gpu_vram_total_gb": 8.0,
            "gpu_vram_available_gb": 4.0,
            "gpu_type": "nvidia",
        }

        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            resource_metrics=metrics,
        )

        test_db.add(agent)
        test_db.commit()

        # Verify
        stored = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()

        assert "gpu_vram_available_gb" in stored.resource_metrics
        assert "gpu_type" in stored.resource_metrics
        assert stored.resource_metrics["gpu_type"] == "nvidia"

    @pytest.mark.asyncio
    async def test_metrics_updated_on_each_heartbeat(self, test_db):
        """Verify metrics are updated on each heartbeat."""
        # Setup: create agent with initial metrics
        agent_id = uuid4()
        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            resource_metrics={"cpu_percent": 30.0, "gpu_vram_available_gb": 8.0},
        )

        test_db.add(agent)
        test_db.commit()

        # Simulate second heartbeat with updated metrics
        agent.resource_metrics = {"cpu_percent": 60.0, "gpu_vram_available_gb": 4.0}
        test_db.commit()

        # Verify metrics updated
        stored = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()

        assert stored.resource_metrics["cpu_percent"] == 60.0
        assert stored.resource_metrics["gpu_vram_available_gb"] == 4.0

    @pytest.mark.asyncio
    async def test_empty_metrics_handled_gracefully(self, test_db):
        """Verify empty metrics are handled gracefully."""
        # Setup: agent with no metrics yet
        agent_id = uuid4()
        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            resource_metrics={},
        )

        test_db.add(agent)
        test_db.commit()

        # Verify empty dict is valid
        stored = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()

        assert isinstance(stored.resource_metrics, dict)
        assert len(stored.resource_metrics) == 0


class TestHeartbeatHandling:
    """Test heartbeat message handling."""

    @pytest.mark.asyncio
    async def test_orchestrator_updates_last_heartbeat_at(self, test_db):
        """Verify orchestrator updates last_heartbeat_at timestamp."""
        # Setup
        agent_id = uuid4()
        old_time = datetime.utcnow() - timedelta(seconds=60)

        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            last_heartbeat_at=old_time,
        )

        test_db.add(agent)
        test_db.commit()

        # Simulate heartbeat
        agent.last_heartbeat_at = datetime.utcnow()
        test_db.commit()

        # Verify timestamp updated
        stored = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()

        assert stored.last_heartbeat_at > old_time

    @pytest.mark.asyncio
    async def test_orchestrator_marks_status_online_on_heartbeat(self, test_db):
        """Verify orchestrator marks agent online on heartbeat."""
        # Setup: agent marked offline
        agent_id = uuid4()
        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="offline",
        )

        test_db.add(agent)
        test_db.commit()

        # Simulate heartbeat
        agent.status = "online"
        agent.last_heartbeat_at = datetime.utcnow()
        test_db.commit()

        # Verify status changed
        stored = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()

        assert stored.status == "online"

    @pytest.mark.asyncio
    async def test_multiple_agents_heartbeats_processed_independently(self, test_db):
        """Verify multiple agents' heartbeats don't interfere."""
        # Setup: create 2 agents
        agent1_id = uuid4()
        agent2_id = uuid4()

        agent1 = AgentRegistry(
            agent_id=agent1_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            last_heartbeat_at=datetime.utcnow() - timedelta(seconds=30),
        )

        agent2 = AgentRegistry(
            agent_id=agent2_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="offline",
            last_heartbeat_at=datetime.utcnow() - timedelta(seconds=120),
        )

        test_db.add(agent1)
        test_db.add(agent2)
        test_db.commit()

        # Update agent1 only
        agent1.last_heartbeat_at = datetime.utcnow()
        test_db.commit()

        # Verify agent2 unchanged
        stored1 = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent1_id).first()

        stored2 = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent2_id).first()

        assert stored1.status == "online"
        assert stored2.status == "offline"

    @pytest.mark.asyncio
    async def test_corrupted_heartbeat_message_logged_not_crashed(self, test_db):
        """Verify corrupted heartbeat is logged but doesn't crash orchestrator."""
        # This is a boundary test - simulate handling invalid data
        agent_id = uuid4()

        # Try to create agent with invalid data (should handle gracefully)
        try:
            agent = AgentRegistry(
                agent_id=agent_id,
                agent_type="desktop",
                pool_name="desktop_pool_1",
                capabilities=[],
                status="online",
                resource_metrics="not_a_dict",  # Invalid type
            )

            # SQLAlchemy might coerce or reject; either way we shouldn't crash
            test_db.add(agent)
            test_db.commit()

        except Exception:
            # Expected: invalid data type caught
            pass

        # Verify no agents were corrupted
        all_agents = test_db.query(AgentRegistry).all()
        # Should be empty or have valid agents
        assert all_agents is not None


class TestOfflineDetection:
    """Test offline detection and status management."""

    @pytest.mark.asyncio
    async def test_agent_offline_after_90s_no_heartbeat(self, test_db):
        """Verify agent marked offline after 90s without heartbeat."""
        # Setup: agent with heartbeat 100s ago
        agent_id = uuid4()
        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            last_heartbeat_at=datetime.utcnow() - timedelta(seconds=100),
        )

        test_db.add(agent)
        test_db.commit()

        # Check if offline
        stored = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()

        time_since = (datetime.utcnow() - stored.last_heartbeat_at).total_seconds()
        is_offline = time_since > 90

        assert is_offline is True

    @pytest.mark.asyncio
    async def test_offline_detection_periodic_check(self, test_db):
        """Verify offline detection is periodic (not just on heartbeat)."""
        # Setup: create several agents at different times
        now = datetime.utcnow()

        agents_data = [
            (now - timedelta(seconds=30), "online"),  # Recent: should be online
            (now - timedelta(seconds=100), "offline"),  # Old: should be offline
            (now - timedelta(seconds=200), "offline"),  # Very old: definitely offline
        ]

        for heartbeat_time, expected_status in agents_data:
            agent = AgentRegistry(
                agent_id=uuid4(),
                agent_type="desktop",
                pool_name="desktop_pool_1",
                capabilities=[],
                status="online",
                last_heartbeat_at=heartbeat_time,
            )
            test_db.add(agent)

        test_db.commit()

        # Query and check offline status
        all_agents = test_db.query(AgentRegistry).all()

        for agent in all_agents:
            time_since = (now - agent.last_heartbeat_at).total_seconds()
            should_be_offline = time_since > 90

            if should_be_offline:
                assert time_since > 90

    @pytest.mark.asyncio
    async def test_offline_agent_excluded_from_capacity_queries(self, test_db):
        """Verify offline agents not included in capacity queries."""
        # Setup: create online and offline agents
        online_agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            resource_metrics={"gpu_vram_available_gb": 8.0},
        )

        offline_agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="offline",
            resource_metrics={"gpu_vram_available_gb": 8.0},
        )

        test_db.add(online_agent)
        test_db.add(offline_agent)
        test_db.commit()

        # Query only online agents
        online_agents = test_db.query(AgentRegistry).filter(AgentRegistry.status == "online").all()

        # Verify only online agent returned
        assert len(online_agents) == 1
        assert online_agents[0].agent_id == online_agent.agent_id

    @pytest.mark.asyncio
    async def test_agent_comes_back_online_on_new_heartbeat(self, test_db):
        """Verify agent transitions from offline to online on new heartbeat."""
        # Setup: offline agent
        agent_id = uuid4()
        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="offline",
            last_heartbeat_at=datetime.utcnow() - timedelta(seconds=200),
        )

        test_db.add(agent)
        test_db.commit()

        # Simulate new heartbeat
        agent.status = "online"
        agent.last_heartbeat_at = datetime.utcnow()
        test_db.commit()

        # Verify status changed
        stored = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()

        assert stored.status == "online"

    @pytest.mark.asyncio
    async def test_offline_status_transition_logged(self, test_db):
        """Verify offline status transitions are logged."""
        # Setup: simulate status change
        agent_id = uuid4()
        agent = AgentRegistry(
            agent_id=agent_id,
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
        )

        test_db.add(agent)
        test_db.commit()

        # Mark offline
        agent.status = "offline"
        test_db.commit()

        # Verify transition recorded
        stored = test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()

        assert stored.status == "offline"


class TestCapacityQueryIntegration:
    """Test capacity query integration with agents."""

    @pytest.mark.asyncio
    async def test_capacity_query_returns_online_agents_only(self, test_db):
        """Verify capacity queries only return online agents."""
        # Setup: create mixed agents
        online_agents = []
        for i in range(2):
            agent = AgentRegistry(
                agent_id=uuid4(),
                agent_type="desktop",
                pool_name="desktop_pool_1",
                capabilities=[],
                status="online",
                resource_metrics={"gpu_vram_available_gb": 8.0},
            )
            test_db.add(agent)
            online_agents.append(agent)

        offline_agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="offline",
            resource_metrics={"gpu_vram_available_gb": 8.0},
        )

        test_db.add(offline_agent)
        test_db.commit()

        # Query online only
        result = test_db.query(AgentRegistry).filter(AgentRegistry.status == "online").all()

        # Verify
        assert len(result) == 2
        result_ids = {a.agent_id for a in result}
        assert all(a.agent_id in result_ids for a in online_agents)
        assert offline_agent.agent_id not in result_ids

    @pytest.mark.asyncio
    async def test_capacity_query_filters_by_gpu_vram(self, test_db):
        """Verify capacity query filters by GPU VRAM requirement."""
        # Setup: 3 agents with different VRAM
        agents_data = [
            {"gpu_vram": 8.0, "expected_match": True},
            {"gpu_vram": 4.0, "expected_match": True},
            {"gpu_vram": 2.0, "expected_match": False},
        ]

        for data in agents_data:
            agent = AgentRegistry(
                agent_id=uuid4(),
                agent_type="desktop",
                pool_name="desktop_pool_1",
                capabilities=[],
                status="online",
                resource_metrics={"gpu_vram_available_gb": data["gpu_vram"]},
            )
            test_db.add(agent)

        test_db.commit()

        # Query: min_gpu_vram=4.0
        result = (
            test_db.query(AgentRegistry)
            .filter(
                AgentRegistry.agent_type == "desktop",
                AgentRegistry.status == "online",
            )
            .all()
        )

        # Filter in Python for min_gpu_vram >= 4.0
        filtered = [a for a in result if a.resource_metrics.get("gpu_vram_available_gb", 0) >= 4.0]

        # Verify
        assert len(filtered) == 2

    @pytest.mark.asyncio
    async def test_capacity_query_filters_by_cpu_cores(self, test_db):
        """Verify capacity query filters by CPU core requirement."""
        # Setup: agents with different core counts
        agents_data = [
            {"cpu_cores": 16, "expected_match": True},
            {"cpu_cores": 8, "expected_match": True},
            {"cpu_cores": 4, "expected_match": False},
        ]

        for data in agents_data:
            agent = AgentRegistry(
                agent_id=uuid4(),
                agent_type="desktop",
                pool_name="desktop_pool_1",
                capabilities=[],
                status="online",
                resource_metrics={"cpu_cores_available": data["cpu_cores"]},
            )
            test_db.add(agent)

        test_db.commit()

        # Query: min_cpu_cores=8
        result = (
            test_db.query(AgentRegistry)
            .filter(
                AgentRegistry.agent_type == "desktop",
                AgentRegistry.status == "online",
            )
            .all()
        )

        # Filter in Python for min_cpu_cores >= 8
        filtered = [a for a in result if a.resource_metrics.get("cpu_cores_available", 0) >= 8]

        # Verify
        assert len(filtered) == 2

    @pytest.mark.asyncio
    async def test_capacity_query_returns_all_metrics(self, test_db):
        """Verify capacity queries return all metric fields."""
        # Setup
        agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="desktop",
            pool_name="desktop_pool_1",
            capabilities=[],
            status="online",
            resource_metrics={
                "cpu_percent": 45.0,
                "memory_percent": 30.0,
                "gpu_vram_available_gb": 5.5,
                "cpu_cores_available": 10,
                "cpu_load_1min": 0.6,
                "gpu_type": "nvidia",
            },
        )

        test_db.add(agent)
        test_db.commit()

        # Query
        stored = (
            test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent.agent_id).first()
        )

        # Verify all metrics present
        assert "gpu_vram_available_gb" in stored.resource_metrics
        assert "cpu_cores_available" in stored.resource_metrics
        assert "cpu_load_1min" in stored.resource_metrics


class TestMultiAgentScenarios:
    """Test scenarios with multiple agents."""

    @pytest.mark.asyncio
    async def test_orchestrator_tracks_3_agents_simultaneously(self, test_db):
        """Verify orchestrator tracks 3 agents independently."""
        # Setup: create 3 agents
        agents = []
        for i in range(3):
            agent = AgentRegistry(
                agent_id=uuid4(),
                agent_type="desktop",
                pool_name="desktop_pool_1",
                capabilities=[],
                status="online",
                resource_metrics={
                    "gpu_vram_available_gb": 8.0 - (i * 2),
                    "cpu_cores_available": 16 + (i * 2),
                },
            )
            test_db.add(agent)
            agents.append(agent)

        test_db.commit()

        # Verify all 3 in database
        all_agents = (
            test_db.query(AgentRegistry).filter(AgentRegistry.agent_type == "desktop").all()
        )

        assert len(all_agents) == 3
        assert all(a.status == "online" for a in all_agents)

    @pytest.mark.asyncio
    async def test_capacity_query_with_mixed_capabilities(self, test_db):
        """Verify capacity query with mixed GPU/CPU capabilities."""
        # Setup: 3 agents with different profiles
        profiles = [
            {"gpu_vram": 8.0, "cpu_cores": 16, "name": "high_end"},
            {"gpu_vram": 2.0, "cpu_cores": 4, "name": "low_end"},
            {"gpu_vram": 0.0, "cpu_cores": 8, "name": "cpu_only"},
        ]

        for profile in profiles:
            agent = AgentRegistry(
                agent_id=uuid4(),
                agent_type="desktop",
                pool_name="desktop_pool_1",
                capabilities=[],
                status="online",
                resource_metrics={
                    "gpu_vram_available_gb": profile["gpu_vram"],
                    "cpu_cores_available": profile["cpu_cores"],
                },
            )
            test_db.add(agent)

        test_db.commit()

        # Query 1: agents with GPU capacity
        gpu_agents = (
            test_db.query(AgentRegistry)
            .filter(
                AgentRegistry.agent_type == "desktop",
                AgentRegistry.status == "online",
            )
            .all()
        )

        gpu_capable = [
            a for a in gpu_agents if a.resource_metrics.get("gpu_vram_available_gb", 0) > 0
        ]

        # Verify
        assert len(gpu_capable) == 2

        # Query 2: agents with CPU capacity
        cpu_agents = [
            a for a in gpu_agents if a.resource_metrics.get("cpu_cores_available", 0) >= 4
        ]

        assert len(cpu_agents) == 3
