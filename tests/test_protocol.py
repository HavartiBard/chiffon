"""
Contract tests for agent communication protocol.
Validates all message types, field validators, correlation IDs, and serialization.
"""

from datetime import datetime
from uuid import uuid4

import pytest

from src.common.protocol import (
    ErrorMessage,
    MessageEnvelope,
    StatusUpdate,
    WorkRequest,
    WorkResult,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def valid_message_envelope():
    """Create a valid MessageEnvelope for testing."""
    return MessageEnvelope(
        from_agent="orchestrator",
        to_agent="infra",
        type="work_request",
        payload={"task_id": str(uuid4())},
    )


@pytest.fixture
def valid_work_request():
    """Create a valid WorkRequest for testing."""
    return WorkRequest(
        task_id=uuid4(),
        work_type="deploy_service",
        parameters={"service_name": "kuma"},
        hints={"deadline_seconds": 300},
    )


@pytest.fixture
def valid_work_result():
    """Create a valid WorkResult for testing."""
    return WorkResult(
        task_id=uuid4(),
        status="completed",
        exit_code=0,
        duration_ms=5000,
        agent_id=uuid4(),
    )


@pytest.fixture
def valid_status_update():
    """Create a valid StatusUpdate for testing."""
    return StatusUpdate(
        agent_id=uuid4(),
        agent_type="infra",
        status="online",
        resources={"cpu_percent": 50.0, "gpu_vram_available_gb": 8.0},
    )


@pytest.fixture
def valid_error_message():
    """Create a valid ErrorMessage for testing."""
    return ErrorMessage(
        error_code=5001,
        error_message="Operation timeout",
        context={"timeout_ms": 30000},
    )


# ============================================================================
# MessageEnvelope Validation Tests (10 tests)
# ============================================================================


def test_message_envelope_requires_from_agent():
    """Envelope must specify from_agent."""
    with pytest.raises(ValueError):
        MessageEnvelope(
            to_agent="infra",
            type="work_request",
            payload={},
        )


def test_message_envelope_requires_to_agent():
    """Envelope must specify to_agent."""
    with pytest.raises(ValueError):
        MessageEnvelope(
            from_agent="orchestrator",
            type="work_request",
            payload={},
        )


def test_message_envelope_requires_type():
    """Envelope must specify message type."""
    with pytest.raises(ValueError):
        MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            payload={},
        )


def test_message_envelope_validates_agent_type_values():
    """Agent types must be one of: orchestrator, infra, desktop, code, research."""
    valid_types = ["orchestrator", "infra", "desktop", "code", "research"]
    for agent_type in valid_types:
        env = MessageEnvelope(
            from_agent=agent_type,
            to_agent="orchestrator",
            type="work_request",
            payload={},
        )
        assert env.from_agent == agent_type

    with pytest.raises(ValueError):
        MessageEnvelope(
            from_agent="invalid_agent",
            to_agent="orchestrator",
            type="work_request",
            payload={},
        )


def test_message_envelope_validates_message_type_values():
    """Message types must be one of: work_request, work_status, work_result, error."""
    valid_types = ["work_request", "work_status", "work_result", "error"]
    for msg_type in valid_types:
        env = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type=msg_type,
            payload={},
        )
        assert env.type == msg_type

    with pytest.raises(ValueError):
        MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="invalid_type",
            payload={},
        )


def test_message_envelope_generates_unique_message_id():
    """Each envelope should have unique message_id."""
    env1 = MessageEnvelope(
        from_agent="orchestrator",
        to_agent="infra",
        type="work_request",
        payload={},
    )
    env2 = MessageEnvelope(
        from_agent="orchestrator",
        to_agent="infra",
        type="work_request",
        payload={},
    )
    assert env1.message_id != env2.message_id


def test_message_envelope_generates_unique_trace_id():
    """Each envelope should have unique trace_id."""
    env1 = MessageEnvelope(
        from_agent="orchestrator",
        to_agent="infra",
        type="work_request",
        payload={},
    )
    env2 = MessageEnvelope(
        from_agent="orchestrator",
        to_agent="infra",
        type="work_request",
        payload={},
    )
    assert env1.trace_id != env2.trace_id


def test_message_envelope_timestamp_defaults_to_utcnow():
    """Timestamp should default to current UTC time."""
    before = datetime.utcnow()
    env = MessageEnvelope(
        from_agent="orchestrator",
        to_agent="infra",
        type="work_request",
        payload={},
    )
    after = datetime.utcnow()
    assert before <= env.timestamp <= after


def test_message_envelope_priority_must_be_1_to_5():
    """Priority must be between 1 and 5."""
    for priority in [1, 2, 3, 4, 5]:
        env = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="work_request",
            priority=priority,
            payload={},
        )
        assert env.priority == priority

    with pytest.raises(ValueError):
        MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="work_request",
            priority=0,
            payload={},
        )

    with pytest.raises(ValueError):
        MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="work_request",
            priority=6,
            payload={},
        )


def test_message_envelope_to_json_and_from_json_round_trip():
    """Envelope should serialize and deserialize correctly."""
    original = MessageEnvelope(
        from_agent="orchestrator",
        to_agent="infra",
        type="work_request",
        priority=2,
        payload={"work_type": "deploy"},
    )
    json_str = original.to_json()
    restored = MessageEnvelope.from_json(json_str)
    assert restored.message_id == original.message_id
    assert restored.trace_id == original.trace_id
    assert restored.from_agent == original.from_agent
    assert restored.priority == original.priority


# ============================================================================
# WorkRequest Validation Tests (5 tests)
# ============================================================================


def test_work_request_requires_task_id():
    """WorkRequest must specify task_id."""
    with pytest.raises(ValueError):
        WorkRequest(work_type="deploy_service")


def test_work_request_requires_work_type():
    """WorkRequest must specify work_type."""
    with pytest.raises(ValueError):
        WorkRequest(task_id=uuid4())


def test_work_request_accepts_optional_parameters():
    """WorkRequest parameters are optional."""
    wr = WorkRequest(task_id=uuid4(), work_type="deploy_service")
    assert wr.parameters == {}


def test_work_request_accepts_optional_hints():
    """WorkRequest hints are optional."""
    wr = WorkRequest(task_id=uuid4(), work_type="deploy_service")
    assert wr.hints == {}


def test_work_request_serializes_to_json():
    """WorkRequest should serialize and deserialize correctly."""
    original = WorkRequest(
        task_id=uuid4(),
        work_type="deploy_service",
        parameters={"service": "kuma"},
        hints={"deadline_seconds": 300},
    )
    json_data = original.model_dump_json()
    restored = WorkRequest.model_validate_json(json_data)
    assert restored.work_type == original.work_type


# ============================================================================
# WorkResult Validation Tests (7 tests)
# ============================================================================


def test_work_result_requires_task_id():
    """WorkResult must specify task_id."""
    with pytest.raises(ValueError):
        WorkResult(
            status="completed",
            exit_code=0,
            duration_ms=5000,
            agent_id=uuid4(),
        )


def test_work_result_requires_status():
    """WorkResult must specify status."""
    with pytest.raises(ValueError):
        WorkResult(
            task_id=uuid4(),
            exit_code=0,
            duration_ms=5000,
            agent_id=uuid4(),
        )


def test_work_result_requires_exit_code():
    """WorkResult must specify exit_code."""
    with pytest.raises(ValueError):
        WorkResult(
            task_id=uuid4(),
            status="completed",
            duration_ms=5000,
            agent_id=uuid4(),
        )


def test_work_result_requires_duration_ms():
    """WorkResult must specify duration_ms."""
    with pytest.raises(ValueError):
        WorkResult(
            task_id=uuid4(),
            status="completed",
            exit_code=0,
            agent_id=uuid4(),
        )


def test_work_result_requires_agent_id():
    """WorkResult must specify agent_id."""
    with pytest.raises(ValueError):
        WorkResult(
            task_id=uuid4(),
            status="completed",
            exit_code=0,
            duration_ms=5000,
        )


def test_work_result_failed_must_have_error_message():
    """Failed WorkResult must include error_message."""
    with pytest.raises(ValueError):
        WorkResult(
            task_id=uuid4(),
            status="failed",
            exit_code=1,
            duration_ms=5000,
            agent_id=uuid4(),
        )


def test_work_result_completed_can_omit_error_message():
    """Completed WorkResult can omit error_message."""
    result = WorkResult(
        task_id=uuid4(),
        status="completed",
        exit_code=0,
        duration_ms=5000,
        agent_id=uuid4(),
    )
    assert result.error_message is None


def test_work_result_validates_status_values():
    """WorkResult status must be completed, failed, or cancelled."""
    valid_statuses = ["completed", "failed", "cancelled"]
    for status_val in valid_statuses:
        error_msg = "test error" if status_val == "failed" else None
        result = WorkResult(
            task_id=uuid4(),
            status=status_val,
            exit_code=0 if status_val != "failed" else 1,
            duration_ms=5000,
            agent_id=uuid4(),
            error_message=error_msg,
        )
        assert result.status == status_val

    with pytest.raises(ValueError):
        WorkResult(
            task_id=uuid4(),
            status="invalid_status",
            exit_code=0,
            duration_ms=5000,
            agent_id=uuid4(),
        )


# ============================================================================
# StatusUpdate Validation Tests (5 tests)
# ============================================================================


def test_status_update_requires_agent_id():
    """StatusUpdate must specify agent_id."""
    with pytest.raises(ValueError):
        StatusUpdate(agent_type="infra", status="online")


def test_status_update_requires_agent_type():
    """StatusUpdate must specify agent_type."""
    with pytest.raises(ValueError):
        StatusUpdate(agent_id=uuid4(), status="online")


def test_status_update_requires_status_field():
    """StatusUpdate must specify status field."""
    with pytest.raises(ValueError):
        StatusUpdate(agent_id=uuid4(), agent_type="infra")


def test_status_update_validates_status_values():
    """StatusUpdate status must be online, offline, or busy."""
    valid_statuses = ["online", "offline", "busy"]
    for status_val in valid_statuses:
        update = StatusUpdate(
            agent_id=uuid4(),
            agent_type="infra",
            status=status_val,
        )
        assert update.status == status_val

    with pytest.raises(ValueError):
        StatusUpdate(
            agent_id=uuid4(),
            agent_type="infra",
            status="invalid_status",
        )


def test_status_update_includes_resource_metrics():
    """StatusUpdate should include resource metrics."""
    update = StatusUpdate(
        agent_id=uuid4(),
        agent_type="infra",
        status="online",
        resources={"cpu_percent": 45.5, "gpu_vram_available_gb": 8.0},
    )
    assert update.resources["cpu_percent"] == 45.5


# ============================================================================
# ErrorMessage Validation Tests (4 tests)
# ============================================================================


def test_error_message_requires_error_code():
    """ErrorMessage must specify error_code."""
    with pytest.raises(ValueError):
        ErrorMessage(error_message="Test error")


def test_error_message_requires_error_message_field():
    """ErrorMessage must specify error_message."""
    with pytest.raises(ValueError):
        ErrorMessage(error_code=5001)


def test_error_message_error_code_must_be_1000_to_9999():
    """ErrorMessage error_code must be between 1000 and 9999."""
    valid_error = ErrorMessage(error_code=5001, error_message="Test")
    assert valid_error.error_code == 5001

    with pytest.raises(ValueError):
        ErrorMessage(error_code=999, error_message="Test")

    with pytest.raises(ValueError):
        ErrorMessage(error_code=10000, error_message="Test")


def test_error_message_accepts_optional_context():
    """ErrorMessage context is optional."""
    error = ErrorMessage(error_code=5001, error_message="Test")
    assert error.context == {}


# ============================================================================
# Correlation ID Tests (5 tests)
# ============================================================================


def test_trace_id_propagates_in_round_trip():
    """Trace ID should be preserved through serialization."""
    trace_id = uuid4()
    env = MessageEnvelope(
        from_agent="orchestrator",
        to_agent="infra",
        type="work_request",
        trace_id=trace_id,
        payload={},
    )
    json_str = env.to_json()
    restored = MessageEnvelope.from_json(json_str)
    assert restored.trace_id == trace_id


def test_request_id_propagates_in_round_trip():
    """Request ID should be preserved through serialization."""
    request_id = uuid4()
    env = MessageEnvelope(
        from_agent="orchestrator",
        to_agent="infra",
        type="work_request",
        request_id=request_id,
        payload={},
    )
    json_str = env.to_json()
    restored = MessageEnvelope.from_json(json_str)
    assert restored.request_id == request_id


def test_trace_id_can_be_set_explicitly():
    """Trace ID can be explicitly set."""
    trace_id = uuid4()
    env = MessageEnvelope(
        from_agent="orchestrator",
        to_agent="infra",
        type="work_request",
        trace_id=trace_id,
        payload={},
    )
    assert env.trace_id == trace_id


def test_request_id_can_be_set_explicitly():
    """Request ID can be explicitly set."""
    request_id = uuid4()
    env = MessageEnvelope(
        from_agent="orchestrator",
        to_agent="infra",
        type="work_request",
        request_id=request_id,
        payload={},
    )
    assert env.request_id == request_id


def test_multiple_messages_have_different_trace_ids():
    """Multiple messages should have different trace IDs by default."""
    env1 = MessageEnvelope(
        from_agent="orchestrator",
        to_agent="infra",
        type="work_request",
        payload={},
    )
    env2 = MessageEnvelope(
        from_agent="orchestrator",
        to_agent="infra",
        type="work_request",
        payload={},
    )
    assert env1.trace_id != env2.trace_id


# ============================================================================
# Timestamp Tests (3 tests)
# ============================================================================


def test_timestamp_parses_iso_8601_string():
    """Timestamp should parse ISO 8601 format."""
    iso_time = "2026-01-19T10:30:00.123456"
    env = MessageEnvelope(
        from_agent="orchestrator",
        to_agent="infra",
        type="work_request",
        timestamp=iso_time,
        payload={},
    )
    assert isinstance(env.timestamp, datetime)


def test_timestamp_parses_iso_8601_string_with_z_suffix():
    """Timestamp should parse ISO 8601 with Z suffix."""
    iso_time = "2026-01-19T10:30:00Z"
    env = MessageEnvelope(
        from_agent="orchestrator",
        to_agent="infra",
        type="work_request",
        timestamp=iso_time,
        payload={},
    )
    assert isinstance(env.timestamp, datetime)


def test_timestamp_rejects_invalid_format():
    """Timestamp should reject invalid format."""
    with pytest.raises(ValueError):
        MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="work_request",
            timestamp="not-a-timestamp",
            payload={},
        )


# ============================================================================
# Error Condition Tests (3 tests)
# ============================================================================


def test_message_with_invalid_json_fails_to_deserialize():
    """Invalid JSON should fail deserialization."""
    with pytest.raises(ValueError):
        MessageEnvelope.from_json("{invalid json")


def test_message_with_missing_required_field_fails():
    """Missing required field should fail validation."""
    json_str = '{"from_agent": "orchestrator", "type": "work_request", "payload": {}}'
    with pytest.raises(ValueError):
        MessageEnvelope.from_json(json_str)


def test_message_with_type_mismatch_fails():
    """Type mismatch should fail validation."""
    with pytest.raises(ValueError):
        MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="work_request",
            payload={},
            priority="not_an_int",  # type: ignore
        )
