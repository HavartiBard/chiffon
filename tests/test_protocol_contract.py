"""
Contract tests for the Chiffon agent protocol.
Validates that all protocol message types conform to specification.
"""

import json
from datetime import datetime
from uuid import uuid4

import pytest

from src.common.exceptions import (
    AgentUnavailableError,
    AuthenticationFailedError,
    InvalidMessageFormatError,
    ResourceLimitExceededError,
    TimeoutError,
    UnsupportedWorkTypeError,
)
from src.common.protocol import (
    ErrorMessage,
    MessageEnvelope,
    ResourcesUsed,
    Step,
    WorkRequest,
    WorkResult,
    WorkStatus,
)

# Fixtures


@pytest.fixture
def sample_task_id():
    """Sample task ID for tests."""
    return uuid4()


@pytest.fixture
def valid_work_request(sample_task_id):
    """Valid WorkRequest instance."""
    return WorkRequest(
        task_id=sample_task_id,
        work_type="deploy",
        parameters={"service": "kuma", "version": "1.4.0"},
        hints={"max_duration_seconds": 300},
    )


@pytest.fixture
def valid_step():
    """Valid Step instance."""
    return Step(
        number=1,
        name="Initialize deployment",
        output="Starting Kuma deployment...",
    )


@pytest.fixture
def valid_work_status(sample_task_id, valid_step):
    """Valid WorkStatus instance."""
    return WorkStatus(
        task_id=sample_task_id,
        status="running",
        progress_percent=50,
        step=valid_step,
    )


@pytest.fixture
def valid_resources_used():
    """Valid ResourcesUsed instance."""
    return ResourcesUsed(
        duration_seconds=87,
        gpu_vram_mb=0,
        cpu_time_ms=12450,
    )


@pytest.fixture
def valid_work_result(sample_task_id, valid_resources_used):
    """Valid WorkResult instance."""
    from uuid import uuid4
    return WorkResult(
        task_id=sample_task_id,
        status="completed",
        exit_code=0,
        output="Deployment successful",
        duration_ms=87000,
        agent_id=uuid4(),
        resources_used={
            "duration_seconds": valid_resources_used.duration_seconds,
            "gpu_vram_mb": valid_resources_used.gpu_vram_mb,
            "cpu_time_ms": valid_resources_used.cpu_time_ms,
        },
    )


# Tests: Message Envelope


class TestMessageEnvelopeRequiredFields:
    """Test that MessageEnvelope has all required fields."""

    def test_envelope_required_fields(self):
        """Verify all required fields present and have proper defaults."""
        env = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="work_request",
            payload={},
        )

        assert env.protocol_version == "1.0"
        assert env.message_id is not None
        assert env.trace_id is not None
        assert env.request_id is not None
        assert env.timestamp is not None
        assert env.from_agent == "orchestrator"
        assert env.to_agent == "infra"
        assert env.type == "work_request"

    def test_envelope_custom_fields_optional(self):
        """Verify x_custom_fields is optional."""
        env = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="error",
            payload={},
        )

        assert env.x_custom_fields == {}


# Tests: WorkRequest


class TestWorkRequest:
    """Test WorkRequest message type."""

    def test_work_request_valid(self, valid_work_request):
        """Create and serialize valid WorkRequest."""
        json_str = valid_work_request.model_dump_json()
        json_obj = json.loads(json_str)

        assert json_obj["task_id"] is not None
        assert json_obj["work_type"] == "deploy"
        assert json_obj["parameters"]["service"] == "kuma"
        assert json_obj["hints"]["max_duration_seconds"] == 300

    def test_work_request_round_trip(self, sample_task_id):
        """Serialize and deserialize WorkRequest."""
        original = WorkRequest(
            task_id=sample_task_id,
            work_type="run_playbook",
            parameters={"playbook": "test.yml"},
            hints={"max_memory_mb": 512},
        )

        json_str = original.model_dump_json()
        data = json.loads(json_str)
        restored = WorkRequest(**data)

        assert restored.task_id == original.task_id
        assert restored.work_type == original.work_type
        assert restored.parameters == original.parameters
        assert restored.hints == original.hints

    def test_work_request_defaults(self, sample_task_id):
        """Verify WorkRequest defaults work."""
        req = WorkRequest(
            task_id=sample_task_id,
            work_type="test",
        )

        assert req.parameters == {}
        assert req.hints == {}

    def test_work_request_empty_parameters_ok(self, sample_task_id):
        """Verify empty parameters are acceptable."""
        req = WorkRequest(
            task_id=sample_task_id,
            work_type="simple",
            parameters={},
        )

        assert req.parameters == {}


# Tests: WorkStatus


class TestWorkStatus:
    """Test WorkStatus message type."""

    def test_work_status_valid(self, valid_work_status):
        """Create and serialize valid WorkStatus."""
        json_str = valid_work_status.model_dump_json()
        json_obj = json.loads(json_str)

        assert json_obj["status"] == "running"
        assert json_obj["progress_percent"] == 50
        assert json_obj["step"]["number"] == 1

    def test_progress_percent_valid_range(self, sample_task_id, valid_step):
        """Test progress_percent validation."""
        for percent in [0, 25, 50, 75, 100]:
            status = WorkStatus(
                task_id=sample_task_id,
                status="running",
                progress_percent=percent,
                step=valid_step,
            )
            assert status.progress_percent == percent

    def test_progress_percent_invalid_negative(self, sample_task_id, valid_step):
        """Test progress_percent rejects negative values."""
        with pytest.raises(ValueError):
            WorkStatus(
                task_id=sample_task_id,
                status="running",
                progress_percent=-1,
                step=valid_step,
            )

    def test_progress_percent_invalid_over_100(self, sample_task_id, valid_step):
        """Test progress_percent rejects >100."""
        with pytest.raises(ValueError):
            WorkStatus(
                task_id=sample_task_id,
                status="running",
                progress_percent=101,
                step=valid_step,
            )

    def test_work_status_all_statuses(self, sample_task_id, valid_step):
        """Test all valid status values."""
        for status_val in ["running", "step_completed", "paused"]:
            status = WorkStatus(
                task_id=sample_task_id,
                status=status_val,
                progress_percent=50,
                step=valid_step,
            )
            assert status.status == status_val


# Tests: WorkResult


class TestWorkResult:
    """Test WorkResult message type."""

    def test_work_result_success(self, sample_task_id, valid_resources_used):
        """Create and serialize successful WorkResult."""
        from uuid import uuid4
        result = WorkResult(
            task_id=sample_task_id,
            status="completed",
            exit_code=0,
            output="All done",
            duration_ms=5000,
            agent_id=uuid4(),
            resources_used={
                "duration_seconds": valid_resources_used.duration_seconds,
                "gpu_vram_mb": valid_resources_used.gpu_vram_mb,
            },
        )

        json_str = result.model_dump_json()
        json_obj = json.loads(json_str)

        assert json_obj["status"] == "completed"
        assert json_obj["exit_code"] == 0
        assert json_obj["resources_used"]["duration_seconds"] == 87

    def test_work_result_failure(self, sample_task_id, valid_resources_used):
        """Create and serialize failed WorkResult."""
        from uuid import uuid4
        result = WorkResult(
            task_id=sample_task_id,
            status="failed",
            exit_code=1,
            output="Error occurred",
            error_message="Deployment failed",
            duration_ms=3000,
            agent_id=uuid4(),
            resources_used={"gpu_vram_mb": 0},
        )

        assert result.status == "failed"
        assert result.exit_code == 1

    def test_work_result_status_values(self, sample_task_id, valid_resources_used):
        """Test all valid status values."""
        from uuid import uuid4
        for status_val in ["completed", "failed", "cancelled"]:
            kwargs = {
                "task_id": sample_task_id,
                "status": status_val,
                "exit_code": 0,
                "duration_ms": 1000,
                "agent_id": uuid4(),
                "resources_used": {"cpu_time_ms": 100},
            }
            # error_message required for failed status
            if status_val == "failed":
                kwargs["error_message"] = "Task failed"
            result = WorkResult(**kwargs)
            assert result.status == status_val


# Tests: ResourcesUsed


class TestResourcesUsed:
    """Test ResourcesUsed nested type."""

    def test_resources_used_defaults(self):
        """Test ResourcesUsed defaults."""
        resources = ResourcesUsed(duration_seconds=100)

        assert resources.duration_seconds == 100
        assert resources.gpu_vram_mb == 0
        assert resources.cpu_time_ms == 0

    def test_resources_used_all_fields(self):
        """Test ResourcesUsed with all fields."""
        resources = ResourcesUsed(
            duration_seconds=50,
            gpu_vram_mb=256,
            cpu_time_ms=5000,
        )

        assert resources.duration_seconds == 50
        assert resources.gpu_vram_mb == 256
        assert resources.cpu_time_ms == 5000


# Tests: ErrorMessage


class TestErrorMessage:
    """Test ErrorMessage type."""

    def test_error_message_valid(self):
        """Create and serialize valid ErrorMessage."""
        error = ErrorMessage(
            error_code=5001,
            error_message="Timeout occurred",
            context={"retries": 3},
        )

        json_str = error.model_dump_json()
        json_obj = json.loads(json_str)

        assert json_obj["error_code"] == 5001
        assert json_obj["error_message"] == "Timeout occurred"
        assert json_obj["context"]["retries"] == 3

    def test_error_message_no_context(self):
        """Test ErrorMessage without context."""
        error = ErrorMessage(
            error_code=5003,
            error_message="Invalid message",
        )

        assert error.error_code == 5003
        assert error.context == {}

    def test_error_codes_all_valid(self):
        """Test all valid error codes."""
        for code in [5001, 5002, 5003, 5004, 5005, 5006]:
            error = ErrorMessage(
                error_code=code,
                error_message=f"Error {code}",
            )
            assert error.error_code == code

    def test_error_code_range_minimum(self):
        """Test error code below minimum is rejected."""
        with pytest.raises(ValueError):
            ErrorMessage(
                error_code=999,
                error_message="Below range",
            )

    def test_error_code_range_maximum(self):
        """Test error code above maximum is rejected."""
        with pytest.raises(ValueError):
            ErrorMessage(
                error_code=10000,
                error_message="Above range",
            )


# Tests: Timestamp Validation


class TestTimestampValidation:
    """Test timestamp validation."""

    def test_timestamp_iso_8601_default(self):
        """Test timestamp defaults to ISO 8601."""
        env = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="error",
            payload={},
        )

        # Should be a datetime
        assert isinstance(env.timestamp, datetime)

    def test_timestamp_iso_string_accepted(self):
        """Test ISO string timestamp accepted."""
        iso_time = "2026-01-19T04:21:04Z"
        env = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="error",
            payload={},
            timestamp=iso_time,
        )

        assert env.timestamp is not None

    def test_timestamp_datetime_accepted(self):
        """Test datetime object accepted."""
        now = datetime.utcnow()
        env = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="error",
            payload={},
            timestamp=now,
        )

        assert env.timestamp == now


# Tests: UUID Fields


class TestUUIDFields:
    """Test UUID field generation and format."""

    def test_message_id_is_uuid(self):
        """Test message_id is valid UUID."""
        env = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="error",
            payload={},
        )

        assert env.message_id is not None
        # Should be a UUID object
        assert str(env.message_id).count("-") == 4

    def test_trace_id_is_uuid(self):
        """Test trace_id is valid UUID."""
        env = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="error",
            payload={},
        )

        assert env.trace_id is not None
        assert str(env.trace_id).count("-") == 4

    def test_request_id_is_uuid(self):
        """Test request_id is valid UUID."""
        env = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="error",
            payload={},
        )

        assert env.request_id is not None
        assert str(env.request_id).count("-") == 4

    def test_uuid_serialization(self):
        """Test UUIDs serialize to JSON strings."""
        req = WorkRequest(
            task_id=uuid4(),
            work_type="test",
        )

        json_str = req.model_dump_json()
        json_obj = json.loads(json_str)

        # UUIDs should serialize as strings
        assert isinstance(json_obj["task_id"], str)
        assert json_obj["task_id"].count("-") == 4


# Tests: Exception Mapping to Error Codes


class TestExceptionErrorCodes:
    """Test exception classes map to correct error codes."""

    def test_timeout_error_code(self):
        """Test TimeoutError has code 5001."""
        exc = TimeoutError("Test timeout")
        assert exc.error_code == 5001

    def test_agent_unavailable_error_code(self):
        """Test AgentUnavailableError has code 5002."""
        exc = AgentUnavailableError("Test unavailable")
        assert exc.error_code == 5002

    def test_invalid_message_format_error_code(self):
        """Test InvalidMessageFormatError has code 5003."""
        exc = InvalidMessageFormatError("Test invalid")
        assert exc.error_code == 5003

    def test_authentication_failed_error_code(self):
        """Test AuthenticationFailedError has code 5004."""
        exc = AuthenticationFailedError("Test auth failed")
        assert exc.error_code == 5004

    def test_resource_limit_exceeded_error_code(self):
        """Test ResourceLimitExceededError has code 5005."""
        exc = ResourceLimitExceededError("Test resource limit")
        assert exc.error_code == 5005

    def test_unsupported_work_type_error_code(self):
        """Test UnsupportedWorkTypeError has code 5006."""
        exc = UnsupportedWorkTypeError("Test unsupported")
        assert exc.error_code == 5006

    def test_exception_with_context(self):
        """Test exception stores context."""
        context = {"key": "value", "retries": 3}
        exc = TimeoutError("Test", context=context)

        assert exc.context == context
        assert "key" in exc.context

    def test_exception_string_representation(self):
        """Test exception formats as string."""
        exc = TimeoutError("Test message", context={"retries": 3})
        exc_str = str(exc)

        assert "[5001]" in exc_str
        assert "Test message" in exc_str
        assert "retries" in exc_str


# Tests: Step


class TestStep:
    """Test Step nested type."""

    def test_step_valid(self):
        """Create and serialize valid Step."""
        step = Step(
            number=1,
            name="Deploy service",
            output="Starting...",
        )

        assert step.number == 1
        assert step.name == "Deploy service"
        assert step.output == "Starting..."

    def test_step_default_output(self):
        """Test Step output defaults to empty string."""
        step = Step(
            number=1,
            name="Test",
        )

        assert step.output == ""


# Tests: Full Round-Trip Serialization


class TestRoundTripSerialization:
    """Test complete message serialization and deserialization."""

    def test_work_request_envelope_round_trip(self, sample_task_id):
        """Test work_request message round-trip."""
        # Create payload
        payload = WorkRequest(
            task_id=sample_task_id,
            work_type="deploy",
            parameters={"service": "test"},
        ).model_dump()

        # Wrap in envelope
        env = MessageEnvelope(
            from_agent="orchestrator",
            to_agent="infra",
            type="work_request",
            payload=payload,
        )

        # Serialize to JSON
        json_str = env.model_dump_json()
        json_obj = json.loads(json_str)

        # Restore from JSON
        restored = MessageEnvelope(**json_obj)

        # Verify
        assert restored.from_agent == env.from_agent
        assert restored.to_agent == env.to_agent
        assert restored.type == env.type
        assert restored.payload["work_type"] == "deploy"

    def test_work_result_envelope_round_trip(self, sample_task_id):
        """Test work_result message round-trip."""
        from uuid import uuid4
        # Create payload
        resources = ResourcesUsed(
            duration_seconds=100,
            gpu_vram_mb=256,
        )
        payload = WorkResult(
            task_id=sample_task_id,
            status="completed",
            exit_code=0,
            duration_ms=100000,
            agent_id=uuid4(),
            resources_used={
                "duration_seconds": resources.duration_seconds,
                "gpu_vram_mb": resources.gpu_vram_mb,
            },
        ).model_dump()

        # Wrap in envelope
        env = MessageEnvelope(
            from_agent="infra",
            to_agent="orchestrator",
            type="work_result",
            payload=payload,
        )

        # Serialize to JSON
        json_str = env.model_dump_json()
        json_obj = json.loads(json_str)

        # Restore from JSON
        restored = MessageEnvelope(**json_obj)

        # Verify
        assert restored.payload["status"] == "completed"
        assert restored.payload["resources_used"]["duration_seconds"] == 100
