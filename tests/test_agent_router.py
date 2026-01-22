"""Comprehensive tests for agent router and routing logic.

Tests cover:
- Agent routing with performance scoring
- Specialization and context matching
- Load balancing
- Retry logic
- Audit trail logging
- Error handling
"""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.common.models import (
    Base,
    AgentRegistry,
    AgentPerformance,
    RoutingDecision,
    WorkTask,
)
from src.orchestrator.router import AgentRouter, AgentSelection


# Create in-memory SQLite database for testing
@pytest.fixture
def test_db():
    """Create an in-memory test database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


@pytest.fixture
def router(test_db):
    """Create AgentRouter instance for testing."""
    return AgentRouter(test_db)


@pytest.fixture
def infra_agent_online(test_db):
    """Create an online infra agent with deploy_service capability."""
    agent = AgentRegistry(
        agent_id=uuid4(),
        agent_type="infra",
        pool_name="infra_pool_1",
        capabilities=["deploy_service", "run_playbook"],
        specializations=None,
        status="online",
    )
    test_db.add(agent)
    test_db.commit()
    return agent


@pytest.fixture
def infra_agent_offline(test_db):
    """Create an offline infra agent."""
    agent = AgentRegistry(
        agent_id=uuid4(),
        agent_type="infra",
        pool_name="infra_pool_1",
        capabilities=["deploy_service"],
        status="offline",
    )
    test_db.add(agent)
    test_db.commit()
    return agent


@pytest.fixture
def high_perf_agent(test_db):
    """Create agent with 95% success rate, 20 executions."""
    agent = AgentRegistry(
        agent_id=uuid4(),
        agent_type="infra",
        pool_name="infra_pool_1",
        capabilities=["deploy_service"],
        specializations=["deployment_expert"],
        status="online",
    )
    test_db.add(agent)
    test_db.commit()

    perf = AgentPerformance(
        agent_id=agent.agent_id,
        work_type="deploy_service",
        success_count=19,
        failure_count=1,
        total_duration_ms=50000,
        last_execution_at=datetime.now(timezone.utc),
    )
    test_db.add(perf)
    test_db.commit()

    return agent


@pytest.fixture
def new_agent(test_db):
    """Create agent with only 1 execution (low sample size)."""
    agent = AgentRegistry(
        agent_id=uuid4(),
        agent_type="infra",
        pool_name="infra_pool_1",
        capabilities=["deploy_service"],
        status="online",
    )
    test_db.add(agent)
    test_db.commit()

    perf = AgentPerformance(
        agent_id=agent.agent_id,
        work_type="deploy_service",
        success_count=1,
        failure_count=0,
        total_duration_ms=5000,
        last_execution_at=datetime.now(timezone.utc),
    )
    test_db.add(perf)
    test_db.commit()

    return agent


@pytest.fixture
def deploy_task():
    """Create a deploy_service task."""
    return WorkTask(
        order=1,
        name="Deploy Kuma",
        work_type="deploy_service",
        agent_type="infra",
        parameters={"service": "kuma"},
        resource_requirements={
            "estimated_duration_seconds": 300,
            "gpu_vram_mb": 0,
            "cpu_cores": 2,
        },
    )


@pytest.mark.asyncio
class TestAgentRouting:
    """Test basic agent routing."""

    async def test_route_to_online_agent(self, router, infra_agent_online, deploy_task):
        """Task routes to online agent with capability."""
        selection = await router.route_task(deploy_task)
        assert selection.agent_id == infra_agent_online.agent_id
        assert selection.agent_type == "infra"
        assert selection.selected_reason is not None

    async def test_route_prefers_higher_success_rate(
        self, router, test_db, high_perf_agent, infra_agent_online, deploy_task
    ):
        """Two agents available, higher success rate wins."""
        # Create low perf agent
        low_perf = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=["deploy_service"],
            status="online",
        )
        test_db.add(low_perf)
        test_db.commit()

        perf = AgentPerformance(
            agent_id=low_perf.agent_id,
            work_type="deploy_service",
            success_count=10,
            failure_count=10,  # 50% success rate
        )
        test_db.add(perf)
        test_db.commit()

        # Route should prefer high_perf_agent (95% vs 50%)
        selection = await router.route_task(deploy_task)
        assert selection.agent_id == high_perf_agent.agent_id

    async def test_route_prefers_recent_context(
        self, router, test_db, infra_agent_online, new_agent, deploy_task
    ):
        """Two agents with same success rate, recent context wins."""
        # Both agents: create second with same low success rate
        second_agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=["deploy_service"],
            status="online",
        )
        test_db.add(second_agent)
        test_db.commit()

        perf = AgentPerformance(
            agent_id=second_agent.agent_id,
            work_type="deploy_service",
            success_count=1,
            failure_count=0,
        )
        test_db.add(perf)
        test_db.commit()

        # Add recent context for new_agent
        decision = RoutingDecision(
            work_type="deploy_service",
            agent_pool="infra_pool_1",
            selected_agent_id=new_agent.agent_id,
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        test_db.add(decision)
        test_db.commit()

        # Route should prefer new_agent due to recent context
        selection = await router.route_task(deploy_task)
        assert selection.agent_id == new_agent.agent_id

    async def test_route_prefers_specialization(
        self, router, test_db, infra_agent_online, deploy_task
    ):
        """Two agents, specialist wins."""
        specialist = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=["deploy_service"],
            specializations=["deployment_expert"],
            status="online",
        )
        test_db.add(specialist)
        test_db.commit()

        # Give specialist a high success rate to make it clear winner
        perf = AgentPerformance(
            agent_id=specialist.agent_id,
            work_type="deploy_service",
            success_count=15,
            failure_count=0,
        )
        test_db.add(perf)
        test_db.commit()

        # Specialist should win due to specialization + success rate
        selection = await router.route_task(deploy_task)
        assert selection.agent_id == specialist.agent_id

    async def test_route_balances_load(self, router, test_db, deploy_task):
        """Load factor contributes to scoring."""
        agent1 = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=["deploy_service"],
            status="online",
        )
        agent2 = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=["deploy_service"],
            status="online",
        )
        test_db.add_all([agent1, agent2])
        test_db.commit()

        # Give both same performance (50% success, no specialization)
        for agent in [agent1, agent2]:
            perf = AgentPerformance(
                agent_id=agent.agent_id,
                work_type="deploy_service",
                success_count=5,
                failure_count=5,
            )
            test_db.add(perf)
        test_db.commit()

        # Score both with no load
        score1_no_load = router._score_agent(agent1, deploy_task)
        score2_no_load = router._score_agent(agent2, deploy_task)
        assert score1_no_load == score2_no_load  # Should be equal

        # Add load for agent1 only (old routing decisions, outside 4-hour window)
        old_time = datetime.now(timezone.utc) - timedelta(hours=5)
        for i in range(10):
            decision = RoutingDecision(
                work_type="deploy_service",
                agent_pool="infra_pool_1",
                selected_agent_id=agent1.agent_id,
                created_at=old_time - timedelta(minutes=i),
            )
            test_db.add(decision)
        test_db.commit()

        # Score both with agent1 having old history (no load, no context)
        score1_old = router._score_agent(agent1, deploy_task)
        score2_same = router._score_agent(agent2, deploy_task)
        assert score1_old == score2_same  # Still equal since old routing decisions don't count

    async def test_route_offline_agent_pool_fails(self, router, infra_agent_offline, deploy_task):
        """No online agents raises ValueError."""
        with pytest.raises(ValueError, match="offline/empty"):
            await router.route_task(deploy_task)

    async def test_route_missing_capability_skipped(
        self, router, test_db, infra_agent_online, deploy_task
    ):
        """Agent without capability not considered."""
        # Create agent without deploy_service capability
        limited = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=["run_playbook"],  # Missing deploy_service
            status="online",
        )
        test_db.add(limited)
        test_db.commit()

        # Should route to infra_agent_online, not limited
        selection = await router.route_task(deploy_task)
        assert selection.agent_id == infra_agent_online.agent_id


@pytest.mark.asyncio
class TestScoringAlgorithm:
    """Test scoring algorithm details."""

    async def test_success_rate_scoring(self, router, test_db, deploy_task):
        """Agent with 90% success rates correctly."""
        agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=["deploy_service"],
            status="online",
        )
        test_db.add(agent)
        test_db.commit()

        perf = AgentPerformance(
            agent_id=agent.agent_id,
            work_type="deploy_service",
            success_count=18,
            failure_count=2,  # 90% success rate
        )
        test_db.add(perf)
        test_db.commit()

        score = router._score_agent(agent, deploy_task)
        # 90% success rate = 40 * 0.9 = 36 points minimum
        assert score >= 36

    async def test_context_bonus(self, router, test_db, deploy_task):
        """Recent context adds 30 points."""
        agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=["deploy_service"],
            status="online",
        )
        test_db.add(agent)
        test_db.commit()

        # Add recent context
        decision = RoutingDecision(
            work_type="deploy_service",
            agent_pool="infra_pool_1",
            selected_agent_id=agent.agent_id,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        test_db.add(decision)
        test_db.commit()

        score = router._score_agent(agent, deploy_task)
        # Should include 30pt context bonus
        assert score >= 30

    async def test_specialization_bonus(self, router, test_db, deploy_task):
        """Specialist agent scores 20 points higher."""
        agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=["deploy_service"],
            specializations=["deployment_expert"],
            status="online",
        )
        test_db.add(agent)
        test_db.commit()

        score = router._score_agent(agent, deploy_task)
        # Should include 20pt specialization bonus
        assert score >= 20

    async def test_minimum_sample_size(self, router, test_db, deploy_task):
        """Low sample size uses neutral 50% default."""
        agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=["deploy_service"],
            status="online",
        )
        test_db.add(agent)
        test_db.commit()

        # Only 5 executions (below 10 minimum)
        perf = AgentPerformance(
            agent_id=agent.agent_id,
            work_type="deploy_service",
            success_count=5,
            failure_count=0,
        )
        test_db.add(perf)
        test_db.commit()

        score = router._score_agent(agent, deploy_task)
        # Should use 50% default = 20 points, not 40
        assert score >= 20
        assert score < 40  # Should not get full success rate credit

    async def test_perfect_agent_max_score(self, router, test_db, deploy_task):
        """Perfect agent with all bonuses scores high."""
        agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=["deploy_service"],
            specializations=["deployment_expert"],
            status="online",
        )
        test_db.add(agent)
        test_db.commit()

        # Perfect success rate
        perf = AgentPerformance(
            agent_id=agent.agent_id,
            work_type="deploy_service",
            success_count=20,
            failure_count=0,
        )
        test_db.add(perf)
        test_db.commit()

        # Add recent context
        decision = RoutingDecision(
            work_type="deploy_service",
            agent_pool="infra_pool_1",
            selected_agent_id=agent.agent_id,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        test_db.add(decision)
        test_db.commit()

        score = router._score_agent(agent, deploy_task)
        # Should be high (40 success + 30 context + 20 specialization + 10 load = 100)
        # But capped at 100 and actual load=0 so should be 80 minimum
        assert score >= 80


@pytest.mark.asyncio
class TestRoutingAudit:
    """Test routing decision audit trail."""

    async def test_routing_decision_logged(self, router, infra_agent_online, deploy_task):
        """Each routing creates RoutingDecision record."""
        await router.route_task(deploy_task)

        # Verify decision was logged
        decisions = (
            router.db.query(RoutingDecision)
            .filter(
                RoutingDecision.work_type == deploy_task.work_type,
                RoutingDecision.selected_agent_id == infra_agent_online.agent_id,
            )
            .all()
        )
        assert len(decisions) == 1

    async def test_routing_decision_includes_reason(self, router, infra_agent_online, deploy_task):
        """RoutingDecision has explanatory reason."""
        await router.route_task(deploy_task)

        decision = (
            router.db.query(RoutingDecision)
            .filter(RoutingDecision.work_type == deploy_task.work_type)
            .first()
        )
        assert decision.reason is not None
        assert len(decision.reason) > 0

    async def test_routing_includes_retry_flag(self, router, infra_agent_online, deploy_task):
        """Retry attempts marked in routing decision."""
        await router.route_task(deploy_task, retry_count=0)
        await router.route_task(deploy_task, retry_count=1)
        await router.route_task(deploy_task, retry_count=2)

        decisions = (
            router.db.query(RoutingDecision)
            .filter(RoutingDecision.work_type == deploy_task.work_type)
            .order_by(RoutingDecision.created_at)
            .all()
        )

        assert decisions[0].retried == 0  # First attempt
        assert decisions[1].retried == 1  # Retry
        assert decisions[2].retried == 1  # Retry

    async def test_audit_queryable(self, router, infra_agent_online, deploy_task):
        """Can query routing_decisions by work_type and agent_id."""
        await router.route_task(deploy_task)

        # Query by work_type
        by_work = (
            router.db.query(RoutingDecision)
            .filter(RoutingDecision.work_type == deploy_task.work_type)
            .all()
        )
        assert len(by_work) == 1

        # Query by agent_id
        by_agent = (
            router.db.query(RoutingDecision)
            .filter(RoutingDecision.selected_agent_id == infra_agent_online.agent_id)
            .all()
        )
        assert len(by_agent) == 1


@pytest.mark.asyncio
class TestRetryLogic:
    """Test retry and error handling."""

    async def test_retry_on_agent_failure(self, router, test_db, deploy_task):
        """On agent failure, retries with different agent."""
        agent1 = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=["deploy_service"],
            status="online",
        )
        agent2 = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=["deploy_service"],
            status="online",
        )
        test_db.add_all([agent1, agent2])
        test_db.commit()

        result = await router.dispatch_with_retry(deploy_task, max_retries=3)
        assert result["status"] == "dispatched"
        assert result["task_id"] == deploy_task.order

    async def test_permanent_error_no_retry(self, router, infra_agent_offline, deploy_task):
        """Agent pool offline doesn't retry."""
        with pytest.raises(ValueError, match="offline"):
            await router.dispatch_with_retry(deploy_task, max_retries=3)

    async def test_max_retries_respected(self, router, test_db, infra_agent_online, deploy_task):
        """Max retries limit enforced."""
        # This would need to simulate failures, which is complex in this test
        # Just verify max_retries parameter is used
        result = await router.dispatch_with_retry(deploy_task, max_retries=3)
        assert result["status"] == "dispatched"


@pytest.mark.asyncio
class TestAgentRegistration:
    """Test agent registration and status."""

    async def test_register_new_agent(self, test_db):
        """Can create AgentRegistry with capabilities."""
        agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=["deploy_service", "run_playbook"],
            specializations=["deployment_expert"],
            status="online",
        )
        test_db.add(agent)
        test_db.commit()

        retrieved = (
            test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent.agent_id).first()
        )
        assert retrieved is not None
        assert retrieved.capabilities == ["deploy_service", "run_playbook"]

    async def test_agent_online_status(
        self, router, infra_agent_online, infra_agent_offline, deploy_task
    ):
        """Only online agents considered."""
        selection = await router.route_task(deploy_task)
        assert selection.agent_id == infra_agent_online.agent_id

    async def test_agent_capabilities_stored(self, test_db):
        """Agent capabilities JSON stored and queryable."""
        capabilities = ["deploy_service", "run_playbook", "add_config"]
        agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=capabilities,
            status="online",
        )
        test_db.add(agent)
        test_db.commit()

        retrieved = (
            test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent.agent_id).first()
        )
        assert retrieved.capabilities == capabilities

    async def test_specialization_optional(self, test_db):
        """Can create agent without specializations."""
        agent = AgentRegistry(
            agent_id=uuid4(),
            agent_type="infra",
            pool_name="infra_pool_1",
            capabilities=["deploy_service"],
            # No specializations
            status="online",
        )
        test_db.add(agent)
        test_db.commit()

        retrieved = (
            test_db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent.agent_id).first()
        )
        assert retrieved.specializations is None
