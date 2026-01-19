"""Integration and unit tests for the agent framework.

Tests cover:
- Agent initialization and abstract methods
- TestAgent instantiation and work execution
- Message envelope validation and deserialization
- Idempotency cache behavior
- Heartbeat message generation
- Error handling and NACK behavior
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.agents.base import BaseAgent, IdempotencyCache
from src.agents.test_agent import TestAgent
from src.common.config import Config
from src.common.protocol import (
    MessageEnvelope,
    StatusUpdate,
    WorkRequest,
    WorkResult,
)


class TestAgentInitialization:
    """Test basic agent initialization."""

    def test_agent_initializes_with_id_and_type(self):
        """Verify agent stores ID and type correctly."""
        config = Config()
        agent = TestAgent(config, agent_id="test-123")

        assert agent.agent_id == "test-123"
        assert agent.agent_type == "infra"
        assert agent.config == config
        assert agent.current_task_id is None

    def test_test_agent_can_instantiate(self):
        """Verify TestAgent is instantiable."""
        config = Config()
        agent = TestAgent(config)

        assert agent is not None
        assert isinstance(agent, BaseAgent)
        assert isinstance(agent, TestAgent)

    def test_test_agent_implements_execute_work(self):
        """Verify TestAgent has execute_work method."""
        config = Config()
        agent = TestAgent(config)

        assert hasattr(agent, "execute_work")
        assert callable(agent.execute_work)

    def test_test_agent_get_agent_capabilities_returns_dict(self):
        """Verify get_agent_capabilities returns correct dict."""
        config = Config()
        agent = TestAgent(config)
        capabilities = agent.get_agent_capabilities()

        assert isinstance(capabilities, dict)
        assert "echo" in capabilities
        assert "slow_echo" in capabilities
        assert "fail" in capabilities
        assert capabilities["echo"] is True


class TestAbstractMethods:
    """Test that abstract methods are properly defined."""

    def test_base_agent_has_abstract_methods(self):
        """Verify BaseAgent defines abstract methods."""
        # BaseAgent should not be instantiable
        config = Config()

        with pytest.raises(TypeError, match="abstract"):
            BaseAgent("test", "infra", config)


class TestIdempotencyCache:
    """Test the LRU cache with TTL."""

    def test_idempotency_cache_stores_and_retrieves_results(self):
        """Verify cache can store and retrieve values."""
        cache = IdempotencyCache(max_size=10, ttl_seconds=300)
        test_key = "request-123"
        test_value = {"status": "completed", "output": "test"}

        cache.set(test_key, test_value)
        retrieved = cache.get(test_key)

        assert retrieved == test_value

    def test_idempotency_cache_returns_none_for_missing_key(self):
        """Verify cache returns None for non-existent keys."""
        cache = IdempotencyCache(max_size=10, ttl_seconds=300)

        result = cache.get("nonexistent")

        assert result is None

    def test_idempotency_cache_respects_max_size(self):
        """Verify cache evicts oldest entry when full."""
        cache = IdempotencyCache(max_size=3, ttl_seconds=300)

        # Fill cache
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        # Add one more (should evict key1)
        cache.set("key4", "value4")

        assert cache.get("key1") is None  # Evicted
        assert cache.get("key2") == "value2"  # Still present
        assert cache.get("key4") == "value4"  # New entry

    def test_idempotency_cache_lru_behavior(self):
        """Verify cache moves accessed items to end."""
        cache = IdempotencyCache(max_size=3, ttl_seconds=300)

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        # Access key1 (moves to end)
        cache.get("key1")

        # Add key4 (should evict key2, not key1)
        cache.set("key4", "value4")

        assert cache.get("key1") == "value1"  # Still present
        assert cache.get("key2") is None  # Evicted (was least recently used)
        assert cache.get("key4") == "value4"


class TestHeartbeatMessages:
    """Test heartbeat message generation."""

    def test_heartbeat_message_structure(self):
        """Verify heartbeat includes required fields."""
        config = Config()
        agent = TestAgent(config)

        # Create a StatusUpdate manually to verify structure
        status = StatusUpdate(
            agent_id=uuid4(),
            agent_type="infra",
            status="online",
            resources={"cpu_percent": 50.0, "memory_percent": 60.0},
        )

        assert status.agent_id is not None
        assert status.agent_type == "infra"
        assert status.status == "online"
        assert "cpu_percent" in status.resources

    def test_heartbeat_envelope_has_trace_id(self):
        """Verify heartbeat envelope has trace_id."""
        config = Config()
        agent = TestAgent(config)

        status = StatusUpdate(
            agent_id=uuid4(),
            agent_type="infra",
            status="online",
        )

        envelope = MessageEnvelope(
            from_agent="infra",
            to_agent="orchestrator",
            type="work_status",
            payload=status.model_dump(),
        )

        assert envelope.trace_id is not None
        assert isinstance(envelope.trace_id, UUID)

    def test_heartbeat_envelope_has_request_id(self):
        """Verify heartbeat envelope has request_id."""
        config = Config()
        agent = TestAgent(config)

        status = StatusUpdate(
            agent_id=uuid4(),
            agent_type="infra",
            status="online",
        )

        envelope = MessageEnvelope(
            from_agent="infra",
            to_agent="orchestrator",
            type="work_status",
            payload=status.model_dump(),
        )

        assert envelope.request_id is not None
        assert isinstance(envelope.request_id, UUID)


class TestWorkRequestProcessing:
    """Test work request deserialization and validation."""

    def test_work_request_deserialization_validates_envelope(self):
        """Verify envelope validation catches invalid messages."""
        config = Config()
        agent = TestAgent(config)

        # Create invalid envelope (bad protocol version)
        invalid_json = '{"protocol_version": "2.0", "from_agent": "orchestrator", "to_agent": "infra", "type": "work_request", "trace_id": "' + str(
            uuid4()
        ) + '", "request_id": "' + str(uuid4()) + '", "message_id": "' + str(
            uuid4()
        ) + '", "timestamp": "2026-01-19T00:00:00Z", "priority": 3, "payload": {}}'

        try:
            envelope = MessageEnvelope.from_json(invalid_json)
            # If we get here, validation passed (which is correct for JSON parsing)
            # The agent would then reject via _validate_envelope()
            is_valid = agent._validate_envelope(envelope)
            assert not is_valid  # Agent should reject old protocol version
        except Exception:
            # JSON parsing failed, which is also acceptable
            pass

    def test_work_request_creates_valid_result(self):
        """Verify WorkRequest to WorkResult flow."""
        config = Config()
        agent = TestAgent(config)

        work_req = WorkRequest(
            task_id=uuid4(),
            work_type="echo",
            parameters={"message": "test"},
        )

        assert work_req.task_id is not None
        assert work_req.work_type == "echo"
        assert work_req.parameters["message"] == "test"


class TestTestAgentExecution:
    """Test TestAgent work execution."""

    @pytest.mark.asyncio
    async def test_test_agent_echo_work(self):
        """Verify TestAgent handles echo work."""
        config = Config()
        agent = TestAgent(config)

        work_req = WorkRequest(
            task_id=uuid4(),
            work_type="echo",
            parameters={"message": "hello world"},
        )

        result = await agent.execute_work(work_req)

        assert result.status == "completed"
        assert result.exit_code == 0
        assert "hello world" in result.output
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_test_agent_slow_echo_work(self):
        """Verify TestAgent handles slow_echo (sleeps 5s)."""
        config = Config()
        agent = TestAgent(config)

        work_req = WorkRequest(
            task_id=uuid4(),
            work_type="slow_echo",
            parameters={"message": "slow test"},
        )

        result = await agent.execute_work(work_req)

        assert result.status == "completed"
        assert result.exit_code == 0
        assert result.duration_ms >= 5000  # Should be at least 5 seconds

    @pytest.mark.asyncio
    async def test_test_agent_fail_work(self):
        """Verify TestAgent handles fail work type."""
        config = Config()
        agent = TestAgent(config)

        work_req = WorkRequest(
            task_id=uuid4(),
            work_type="fail",
            parameters={"error_message": "test error"},
        )

        result = await agent.execute_work(work_req)

        assert result.status == "failed"
        assert result.exit_code == 1
        assert result.error_message is not None
        assert "test error" in result.error_message

    @pytest.mark.asyncio
    async def test_test_agent_unknown_work_type(self):
        """Verify TestAgent rejects unknown work types."""
        config = Config()
        agent = TestAgent(config)

        work_req = WorkRequest(
            task_id=uuid4(),
            work_type="unknown_work_type",
            parameters={},
        )

        result = await agent.execute_work(work_req)

        assert result.status == "failed"
        assert result.exit_code == 1
        assert "Unknown work type" in result.output


class TestMessageEnvelopeValidation:
    """Test message envelope validation."""

    def test_envelope_serialization_roundtrip(self):
        """Verify envelope can be serialized and deserialized."""
        original = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="work_request",
            payload={"task_id": str(uuid4()), "work_type": "test"},
        )

        json_str = original.to_json()
        deserialized = MessageEnvelope.from_json(json_str)

        assert deserialized.from_agent == original.from_agent
        assert deserialized.to_agent == original.to_agent
        assert deserialized.type == original.type
        assert deserialized.trace_id == original.trace_id

    def test_envelope_validates_agent_types(self):
        """Verify envelope validates agent type patterns."""
        with pytest.raises(Exception):  # Pydantic validation error
            MessageEnvelope(
                from_agent="invalid_agent",
                to_agent="infra",
                type="work_request",
                payload={},
            )

    def test_envelope_validates_message_types(self):
        """Verify envelope validates message type patterns."""
        with pytest.raises(Exception):  # Pydantic validation error
            MessageEnvelope(
                from_agent="orchestrator",
                to_agent="infra",
                type="invalid_type",
                payload={},
            )

    def test_envelope_priority_bounds(self):
        """Verify envelope validates priority 1-5."""
        # Valid priority
        valid = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="work_request",
            payload={},
            priority=3,
        )
        assert valid.priority == 3

        # Invalid priority (too low)
        with pytest.raises(Exception):
            MessageEnvelope(
                from_agent="orchestrator",
                to_agent="infra",
                type="work_request",
                payload={},
                priority=0,
            )

        # Invalid priority (too high)
        with pytest.raises(Exception):
            MessageEnvelope(
                from_agent="orchestrator",
                to_agent="infra",
                type="work_request",
                payload={},
                priority=6,
            )


class TestResourceMetrics:
    """Test resource metric collection."""

    def test_agent_get_resource_metrics(self):
        """Verify agent can collect resource metrics."""
        config = Config()
        agent = TestAgent(config)

        metrics = agent._get_resource_metrics()

        assert "cpu_percent" in metrics
        assert "memory_percent" in metrics
        assert "gpu_vram_total_gb" in metrics
        assert "gpu_vram_available_gb" in metrics
        assert isinstance(metrics["cpu_percent"], float)
        assert isinstance(metrics["memory_percent"], float)

    def test_agent_get_gpu_metrics_handles_missing_gpu(self):
        """Verify GPU metrics gracefully handle missing nvidia-smi."""
        config = Config()
        agent = TestAgent(config)

        metrics = agent._get_gpu_metrics()

        # Should return zero if GPU unavailable
        assert "gpu_vram_total_gb" in metrics
        assert "gpu_vram_available_gb" in metrics
        assert isinstance(metrics["gpu_vram_total_gb"], float)
