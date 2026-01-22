"""Tests for orchestrator capacity query API endpoints.

Test coverage:
- Single agent capacity queries (get_agent_capacity)
- Multi-agent capacity filtering (get_available_capacity)
- Query parameter validation
- Error handling (404, 400, 500)
- Resource metrics extraction and filtering
"""

import pytest
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.orchestrator.service import OrchestratorService
from src.common.models import AgentRegistry, Base
from src.common.config import Config


# ==================== Fixtures ====================


@pytest.fixture
def test_db():
    """Create an in-memory test database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


@pytest.fixture
def orchestrator_service(test_db: Session) -> OrchestratorService:
    """Create an orchestrator service instance for testing."""
    config = Config()
    service = OrchestratorService(config=config, db_session=test_db)
    return service


@pytest.fixture
def sample_agent_1(test_db: Session) -> AgentRegistry:
    """Create a desktop agent with GPU resources."""
    agent = AgentRegistry(
        agent_id=uuid4(),
        agent_type="desktop",
        pool_name="gpu-pool-1",
        capabilities=["gpu_work", "metrics"],
        status="online",
        last_heartbeat_at=datetime.utcnow(),
        resource_metrics={
            "cpu_percent": 30.0,
            "cpu_cores_physical": 16,
            "cpu_cores_available": 12,
            "cpu_load_1min": 0.5,
            "cpu_load_5min": 0.4,
            "memory_percent": 45.0,
            "memory_available_gb": 8.5,
            "gpu_vram_total_gb": 8.0,
            "gpu_vram_available_gb": 4.0,
            "gpu_type": "nvidia",
        },
    )
    test_db.add(agent)
    test_db.commit()
    test_db.refresh(agent)
    return agent


@pytest.fixture
def sample_agent_2(test_db: Session) -> AgentRegistry:
    """Create a desktop agent with moderate GPU resources."""
    agent = AgentRegistry(
        agent_id=uuid4(),
        agent_type="desktop",
        pool_name="gpu-pool-1",
        capabilities=["gpu_work"],
        status="online",
        last_heartbeat_at=datetime.utcnow(),
        resource_metrics={
            "cpu_percent": 50.0,
            "cpu_cores_physical": 8,
            "cpu_cores_available": 3,
            "cpu_load_1min": 1.2,
            "cpu_load_5min": 1.0,
            "memory_percent": 70.0,
            "memory_available_gb": 2.5,
            "gpu_vram_total_gb": 6.0,
            "gpu_vram_available_gb": 2.0,
            "gpu_type": "nvidia",
        },
    )
    test_db.add(agent)
    test_db.commit()
    test_db.refresh(agent)
    return agent


@pytest.fixture
def sample_agent_3(test_db: Session) -> AgentRegistry:
    """Create a desktop agent with low resources (offline)."""
    agent = AgentRegistry(
        agent_id=uuid4(),
        agent_type="desktop",
        pool_name="gpu-pool-2",
        capabilities=["metrics"],
        status="offline",
        last_heartbeat_at=None,
        resource_metrics={},
    )
    test_db.add(agent)
    test_db.commit()
    test_db.refresh(agent)
    return agent


@pytest.fixture
def sample_agent_4(test_db: Session) -> AgentRegistry:
    """Create a desktop agent without GPU."""
    agent = AgentRegistry(
        agent_id=uuid4(),
        agent_type="desktop",
        pool_name="cpu-pool",
        capabilities=["cpu_work"],
        status="online",
        last_heartbeat_at=datetime.utcnow(),
        resource_metrics={
            "cpu_percent": 20.0,
            "cpu_cores_physical": 4,
            "cpu_cores_available": 3,
            "cpu_load_1min": 0.2,
            "cpu_load_5min": 0.1,
            "memory_percent": 30.0,
            "memory_available_gb": 7.0,
            "gpu_vram_total_gb": 0.0,
            "gpu_vram_available_gb": 0.0,
            "gpu_type": "none",
        },
    )
    test_db.add(agent)
    test_db.commit()
    test_db.refresh(agent)
    return agent


# ==================== Single Agent Capacity Tests ====================


@pytest.mark.asyncio
async def test_get_agent_capacity_valid_agent(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    test_db: Session,
) -> None:
    """Test get_agent_capacity returns correct data for valid agent."""
    capacity = await orchestrator_service.get_agent_capacity(sample_agent_1.agent_id, test_db)

    assert capacity["agent_id"] == str(sample_agent_1.agent_id)
    assert capacity["status"] == "online"
    assert capacity["cpu_cores_available"] == 12
    assert capacity["gpu_vram_available_gb"] == 4.0
    assert capacity["gpu_type"] == "nvidia"


@pytest.mark.asyncio
async def test_get_agent_capacity_nonexistent_agent(
    orchestrator_service: OrchestratorService,
    test_db: Session,
) -> None:
    """Test get_agent_capacity raises ValueError for nonexistent agent."""
    nonexistent_id = uuid4()
    with pytest.raises(ValueError, match="Agent not found"):
        await orchestrator_service.get_agent_capacity(nonexistent_id, test_db)


@pytest.mark.asyncio
async def test_get_agent_capacity_all_fields_present(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    test_db: Session,
) -> None:
    """Test get_agent_capacity returns all required fields."""
    capacity = await orchestrator_service.get_agent_capacity(sample_agent_1.agent_id, test_db)

    required_fields = [
        "agent_id",
        "status",
        "cpu_cores_available",
        "cpu_cores_physical",
        "cpu_load_1min",
        "cpu_load_5min",
        "memory_available_gb",
        "gpu_vram_available_gb",
        "gpu_vram_total_gb",
        "gpu_type",
        "timestamp",
    ]
    for field in required_fields:
        assert field in capacity, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_get_agent_capacity_empty_metrics(
    orchestrator_service: OrchestratorService,
    test_db: Session,
) -> None:
    """Test get_agent_capacity handles agent with empty resource_metrics."""
    agent = AgentRegistry(
        agent_id=uuid4(),
        agent_type="desktop",
        pool_name="test-pool",
        capabilities=[],
        status="online",
        resource_metrics={},
    )
    test_db.add(agent)
    test_db.commit()
    test_db.refresh(agent)

    capacity = await orchestrator_service.get_agent_capacity(agent.agent_id, test_db)

    assert capacity["agent_id"] == str(agent.agent_id)
    assert capacity["cpu_cores_available"] == 0
    assert capacity["gpu_vram_available_gb"] == 0.0


@pytest.mark.asyncio
async def test_get_agent_capacity_timestamp_iso8601(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    test_db: Session,
) -> None:
    """Test get_agent_capacity returns ISO 8601 timestamp."""
    capacity = await orchestrator_service.get_agent_capacity(sample_agent_1.agent_id, test_db)

    timestamp = capacity["timestamp"]
    assert timestamp is not None
    # ISO 8601 format check: should contain T
    assert "T" in timestamp


@pytest.mark.asyncio
async def test_get_agent_capacity_cpu_cores_match(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    test_db: Session,
) -> None:
    """Test get_agent_capacity returns correct CPU cores."""
    capacity = await orchestrator_service.get_agent_capacity(sample_agent_1.agent_id, test_db)

    assert capacity["cpu_cores_available"] == sample_agent_1.resource_metrics["cpu_cores_available"]
    assert capacity["cpu_cores_physical"] == sample_agent_1.resource_metrics["cpu_cores_physical"]


# ==================== Multi-Agent Capacity Filtering Tests ====================


@pytest.mark.asyncio
async def test_get_available_capacity_all_online_agents(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    sample_agent_2: AgentRegistry,
    sample_agent_3: AgentRegistry,
    sample_agent_4: AgentRegistry,
    test_db: Session,
) -> None:
    """Test get_available_capacity returns all online agents with minimal requirements."""
    agents = await orchestrator_service.get_available_capacity(
        min_gpu_vram_gb=0.0,
        min_cpu_cores=1,
        db=test_db,
    )

    # Should return 3 online desktop agents (sample_agent_1, 2, 4)
    assert len(agents) == 3
    agent_ids = {agent["agent_id"] for agent in agents}
    assert str(sample_agent_1.agent_id) in agent_ids
    assert str(sample_agent_2.agent_id) in agent_ids
    assert str(sample_agent_4.agent_id) in agent_ids
    # Offline agent should not be in results
    assert str(sample_agent_3.agent_id) not in agent_ids


@pytest.mark.asyncio
async def test_get_available_capacity_filter_gpu_vram(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    sample_agent_2: AgentRegistry,
    sample_agent_4: AgentRegistry,
    test_db: Session,
) -> None:
    """Test get_available_capacity filters by GPU VRAM requirement."""
    # Require 3GB GPU VRAM
    agents = await orchestrator_service.get_available_capacity(
        min_gpu_vram_gb=3.0,
        min_cpu_cores=1,
        db=test_db,
    )

    # Only sample_agent_1 has >= 3GB
    assert len(agents) == 1
    assert agents[0]["agent_id"] == str(sample_agent_1.agent_id)


@pytest.mark.asyncio
async def test_get_available_capacity_filter_cpu_cores(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    sample_agent_2: AgentRegistry,
    sample_agent_4: AgentRegistry,
    test_db: Session,
) -> None:
    """Test get_available_capacity filters by CPU cores requirement."""
    # Require 10 CPU cores
    agents = await orchestrator_service.get_available_capacity(
        min_gpu_vram_gb=0.0,
        min_cpu_cores=10,
        db=test_db,
    )

    # Only sample_agent_1 has >= 10 cores (12 available)
    assert len(agents) == 1
    assert agents[0]["agent_id"] == str(sample_agent_1.agent_id)


@pytest.mark.asyncio
async def test_get_available_capacity_combined_filters(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    sample_agent_2: AgentRegistry,
    sample_agent_4: AgentRegistry,
    test_db: Session,
) -> None:
    """Test get_available_capacity with both GPU and CPU filters."""
    # Require 2GB GPU and 8 CPU cores
    agents = await orchestrator_service.get_available_capacity(
        min_gpu_vram_gb=2.0,
        min_cpu_cores=8,
        db=test_db,
    )

    # Only sample_agent_1 meets both requirements
    assert len(agents) == 1
    assert agents[0]["agent_id"] == str(sample_agent_1.agent_id)


@pytest.mark.asyncio
async def test_get_available_capacity_no_matches(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    sample_agent_2: AgentRegistry,
    test_db: Session,
) -> None:
    """Test get_available_capacity returns empty list when no agents match."""
    # Require impossible resources
    agents = await orchestrator_service.get_available_capacity(
        min_gpu_vram_gb=100.0,
        min_cpu_cores=1,
        db=test_db,
    )

    assert len(agents) == 0


@pytest.mark.asyncio
async def test_get_available_capacity_excludes_offline(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    sample_agent_3: AgentRegistry,
    test_db: Session,
) -> None:
    """Test get_available_capacity excludes offline agents."""
    agents = await orchestrator_service.get_available_capacity(
        min_gpu_vram_gb=0.0,
        min_cpu_cores=1,
        db=test_db,
    )

    # Offline agent should not be included
    agent_ids = {agent["agent_id"] for agent in agents}
    assert str(sample_agent_3.agent_id) not in agent_ids


@pytest.mark.asyncio
async def test_get_available_capacity_response_structure(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    test_db: Session,
) -> None:
    """Test get_available_capacity response has correct structure."""
    agents = await orchestrator_service.get_available_capacity(
        min_gpu_vram_gb=0.0,
        min_cpu_cores=1,
        db=test_db,
    )

    assert len(agents) > 0
    agent = agents[0]

    required_fields = [
        "agent_id",
        "agent_type",
        "pool_name",
        "status",
        "gpu_vram_available_gb",
        "cpu_cores_available",
        "cpu_load_1min",
        "last_heartbeat_at",
    ]
    for field in required_fields:
        assert field in agent, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_get_available_capacity_agent_type_filter(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    test_db: Session,
) -> None:
    """Test get_available_capacity filters by desktop agent type."""
    # Create an infra agent to verify it's excluded
    infra_agent = AgentRegistry(
        agent_id=uuid4(),
        agent_type="infra",
        pool_name="infra-pool",
        capabilities=["ansible"],
        status="online",
        resource_metrics={
            "cpu_cores_available": 8,
            "gpu_vram_available_gb": 0.0,
        },
    )
    test_db.add(infra_agent)
    test_db.commit()

    agents = await orchestrator_service.get_available_capacity(
        min_gpu_vram_gb=0.0,
        min_cpu_cores=1,
        db=test_db,
    )

    # Infra agent should not be in results
    agent_types = {agent["agent_type"] for agent in agents}
    assert "infra" not in agent_types
    # All returned agents should be desktop type
    for agent in agents:
        assert agent["agent_type"] == "desktop"


@pytest.mark.asyncio
async def test_get_available_capacity_multiple_agents_returned(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    sample_agent_2: AgentRegistry,
    test_db: Session,
) -> None:
    """Test get_available_capacity returns multiple agents when applicable."""
    # Query with low requirements (should match multiple agents)
    agents = await orchestrator_service.get_available_capacity(
        min_gpu_vram_gb=0.0,
        min_cpu_cores=1,
        db=test_db,
    )

    # Should return at least 2 agents (sample_agent_1 and sample_agent_2)
    assert len(agents) >= 2


# ==================== Integration Tests ====================


@pytest.mark.asyncio
async def test_capacity_queries_after_agent_status_change(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    test_db: Session,
) -> None:
    """Test capacity queries reflect agent status changes."""
    # Initial query should find agent
    agents = await orchestrator_service.get_available_capacity(
        min_gpu_vram_gb=0.0,
        min_cpu_cores=1,
        db=test_db,
    )
    assert any(a["agent_id"] == str(sample_agent_1.agent_id) for a in agents)

    # Change agent to offline
    sample_agent_1.status = "offline"
    test_db.commit()

    # Query should not find agent
    agents = await orchestrator_service.get_available_capacity(
        min_gpu_vram_gb=0.0,
        min_cpu_cores=1,
        db=test_db,
    )
    assert not any(a["agent_id"] == str(sample_agent_1.agent_id) for a in agents)


@pytest.mark.asyncio
async def test_capacity_queries_different_requirements(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    test_db: Session,
) -> None:
    """Test capacity queries with various requirement combinations."""
    # Test combinations
    test_cases = [
        (0.0, 1, True),  # Should find agent
        (4.0, 12, True),  # Exact match
        (5.0, 12, False),  # GPU too high
        (4.0, 13, False),  # CPU too high
        (0.0, 12, True),  # Only CPU requirement met
    ]

    for min_gpu, min_cpu, should_find in test_cases:
        agents = await orchestrator_service.get_available_capacity(
            min_gpu_vram_gb=min_gpu,
            min_cpu_cores=min_cpu,
            db=test_db,
        )
        found = any(a["agent_id"] == str(sample_agent_1.agent_id) for a in agents)
        assert found == should_find, (
            f"Query (gpu={min_gpu}, cpu={min_cpu}) expected found={should_find}, " f"got {found}"
        )


@pytest.mark.asyncio
async def test_single_and_multi_agent_queries_consistent(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    test_db: Session,
) -> None:
    """Test single and multi-agent queries return consistent data."""
    # Get single agent capacity
    single_capacity = await orchestrator_service.get_agent_capacity(
        sample_agent_1.agent_id,
        test_db,
    )

    # Get all available agents
    all_agents = await orchestrator_service.get_available_capacity(
        min_gpu_vram_gb=0.0,
        min_cpu_cores=1,
        db=test_db,
    )

    # Find our agent in the list
    agent_in_list = next(
        (a for a in all_agents if a["agent_id"] == str(sample_agent_1.agent_id)),
        None,
    )
    assert agent_in_list is not None

    # Compare consistent fields
    assert single_capacity["agent_id"] == agent_in_list["agent_id"]
    assert single_capacity["status"] == agent_in_list["status"]
    assert single_capacity["gpu_vram_available_gb"] == agent_in_list["gpu_vram_available_gb"]
    assert single_capacity["cpu_cores_available"] == agent_in_list["cpu_cores_available"]


# ==================== Parametrized Tests for Multiple Backends ====================


@pytest.mark.asyncio
async def test_get_agent_capacity_multiple_agents(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    sample_agent_2: AgentRegistry,
    test_db: Session,
) -> None:
    """Test get_agent_capacity works for multiple agents."""
    for agent in [sample_agent_1, sample_agent_2]:
        capacity = await orchestrator_service.get_agent_capacity(agent.agent_id, test_db)
        assert capacity["agent_id"] == str(agent.agent_id)
        assert capacity["status"] == "online"


@pytest.mark.asyncio
async def test_get_available_capacity_ordering_deterministic(
    orchestrator_service: OrchestratorService,
    sample_agent_1: AgentRegistry,
    sample_agent_2: AgentRegistry,
    test_db: Session,
) -> None:
    """Test get_available_capacity returns results in consistent order."""
    agents_1 = await orchestrator_service.get_available_capacity(
        min_gpu_vram_gb=0.0,
        min_cpu_cores=1,
        db=test_db,
    )

    # Query again
    agents_2 = await orchestrator_service.get_available_capacity(
        min_gpu_vram_gb=0.0,
        min_cpu_cores=1,
        db=test_db,
    )

    # Should return same number of agents
    assert len(agents_1) == len(agents_2)
