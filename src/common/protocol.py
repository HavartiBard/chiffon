"""
Protocol models for Chiffon agent communication.
Defines JSON envelope format and message types for orchestrator <-> agent communication.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MessageEnvelope(BaseModel):
    """Base message envelope for all agent protocol messages."""

    model_config = ConfigDict(
        validate_by_name=True,
        use_enum_values=True,
    )

    protocol_version: str = Field(default="1.0", description="Protocol version")
    message_id: UUID = Field(default_factory=uuid4, description="Unique message identifier")
    from_agent: str = Field(
        description="Sender agent type",
        pattern="^(orchestrator|infra|desktop|code|research)$",
    )
    to_agent: str = Field(
        description="Recipient agent type",
        pattern="^(orchestrator|infra|desktop|code|research)$",
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="ISO 8601 timestamp")
    trace_id: UUID = Field(default_factory=uuid4, description="Trace ID for debugging")
    request_id: UUID = Field(
        default_factory=uuid4, description="Request ID for idempotency"
    )
    type: str = Field(
        description="Message type",
        pattern="^(work_request|work_status|work_result|error)$",
    )
    payload: dict[str, Any] = Field(description="Message payload (type-specific)")
    x_custom_fields: dict[str, Any] = Field(
        default_factory=dict, description="Custom fields for extensions"
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_timestamp(cls, v: Any) -> datetime:
        """Ensure timestamp is ISO 8601 format."""
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        raise ValueError("Timestamp must be datetime or ISO 8601 string")


class WorkRequest(BaseModel):
    """Message to initiate work on an agent."""

    model_config = ConfigDict(
        validate_by_name=True,
        use_enum_values=True,
    )

    task_id: UUID = Field(description="Unique task identifier")
    work_type: str = Field(
        description="Type of work to perform (e.g., deploy_service, run_playbook)"
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Work type-specific parameters"
    )
    hints: dict[str, Any] = Field(
        default_factory=dict,
        description="Hints for scheduling (max_duration_seconds, max_memory_mb)",
    )


class Step(BaseModel):
    """A single step in work execution."""

    model_config = ConfigDict(
        validate_by_name=True,
        use_enum_values=True,
    )

    number: int = Field(description="Step sequence number")
    name: str = Field(description="Human-readable step name")
    output: str = Field(default="", description="Step output/log")


class WorkStatus(BaseModel):
    """Status update during long-running work."""

    model_config = ConfigDict(
        validate_by_name=True,
        use_enum_values=True,
    )

    task_id: UUID = Field(description="Task being reported on")
    status: str = Field(
        description="Work status",
        pattern="^(running|step_completed|paused)$",
    )
    progress_percent: int = Field(
        ge=0, le=100, description="Progress as percentage 0-100"
    )
    step: Step = Field(description="Current step information")

    @field_validator("progress_percent")
    @classmethod
    def validate_progress(cls, v: int) -> int:
        """Ensure progress is between 0 and 100."""
        if not (0 <= v <= 100):
            raise ValueError("progress_percent must be between 0 and 100")
        return v


class ResourcesUsed(BaseModel):
    """Resources consumed during work execution."""

    model_config = ConfigDict(
        validate_by_name=True,
        use_enum_values=True,
    )

    duration_seconds: int = Field(description="Total execution time in seconds")
    gpu_vram_mb: int = Field(default=0, description="GPU VRAM used in MB")
    cpu_time_ms: int = Field(default=0, description="CPU time used in milliseconds")


class WorkResult(BaseModel):
    """Final result of completed work."""

    model_config = ConfigDict(
        validate_by_name=True,
        use_enum_values=True,
    )

    task_id: UUID = Field(description="Task that completed")
    status: str = Field(
        description="Completion status",
        pattern="^(success|failed)$",
    )
    exit_code: int = Field(description="Exit code (0=success, >0=failure)")
    output: str = Field(default="", description="Final output/logs")
    resources_used: ResourcesUsed = Field(description="Resources consumed")


class ErrorMessage(BaseModel):
    """Error notification message."""

    model_config = ConfigDict(
        validate_by_name=True,
        use_enum_values=True,
    )

    error_code: int = Field(
        ge=5001, le=5999, description="Error code in range 5001-5999"
    )
    error_message: str = Field(description="Human-readable error message")
    error_context: dict[str, Any] | None = Field(
        default=None, description="Additional error context"
    )

    @field_validator("error_code")
    @classmethod
    def validate_error_code(cls, v: int) -> int:
        """Ensure error code is in valid range."""
        if not (5001 <= v <= 5999):
            raise ValueError("error_code must be between 5001 and 5999")
        return v
