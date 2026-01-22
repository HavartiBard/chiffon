"""
Protocol models for Chiffon agent communication.
Defines JSON envelope format and message types for orchestrator <-> agent communication.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MessageEnvelope(BaseModel):
    """Base message envelope for all agent protocol messages."""

    model_config = ConfigDict(
        validate_by_name=True,
        use_enum_values=True,
        arbitrary_types_allowed=False,
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
    request_id: UUID = Field(default_factory=uuid4, description="Request ID for idempotency")
    type: str = Field(
        description="Message type",
        pattern="^(work_request|work_status|work_result|error)$",
    )
    priority: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Priority level 1-5 for RabbitMQ queue (1=critical, 5=background)",
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

    def to_json(self) -> str:
        """Serialize to JSON string with ISO 8601 timestamps."""
        return self.model_dump_json(
            by_alias=False,
            exclude_none=False,
            indent=None,
        )

    @classmethod
    def from_json(cls, json_str: str) -> "MessageEnvelope":
        """Deserialize from JSON string with validation."""
        return cls.model_validate_json(json_str)


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
    progress_percent: int = Field(ge=0, le=100, description="Progress as percentage 0-100")
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
        arbitrary_types_allowed=False,
    )

    task_id: UUID = Field(description="Task being reported on")
    status: str = Field(
        description="Completion status",
        pattern="^(completed|failed|cancelled)$",
    )
    exit_code: int = Field(description="Process exit code (0=success)")
    output: str = Field(default="", description="Work output/stdout")
    error_message: Optional[str] = Field(default=None, description="Error if status=failed")
    duration_ms: int = Field(description="Total work duration in milliseconds")
    agent_id: UUID = Field(description="Agent that executed the work")
    trace_id: Optional[UUID] = Field(
        default=None, description="Trace ID for debugging (set by agent)"
    )
    request_id: Optional[UUID] = Field(
        default=None, description="Request ID for idempotency (set by agent)"
    )
    resources_used: dict[str, Any] = Field(
        default_factory=dict,
        description="Resource consumption: {cpu_time_ms, memory_peak_mb, gpu_memory_used_mb}",
    )
    analysis_result: Optional[dict[str, Any]] = Field(
        default=None, description="Playbook analysis result from PlaybookAnalyzer (if applicable)"
    )

    @model_validator(mode="after")
    def validate_status_and_error(self) -> "WorkResult":
        """Ensure failed status has error_message."""
        if self.status == "failed" and not self.error_message:
            raise ValueError("error_message is required when status='failed'")
        return self


class StatusUpdate(BaseModel):
    """Agent heartbeat status update."""

    model_config = ConfigDict(
        validate_by_name=True,
        use_enum_values=True,
        arbitrary_types_allowed=False,
    )

    agent_id: UUID = Field(description="Unique agent identifier")
    agent_type: str = Field(pattern="^(orchestrator|infra|desktop|code|research)$")
    status: str = Field(pattern="^(online|offline|busy)$")
    current_task_id: Optional[UUID] = Field(
        default=None, description="Task currently being processed"
    )
    resources: dict[str, Any] = Field(
        default_factory=dict,
        description="Resource metrics: cpu_percent, memory_percent, gpu_vram_available_gb, gpu_vram_total_gb",
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ErrorMessage(BaseModel):
    """Error notification message."""

    model_config = ConfigDict(
        validate_by_name=True,
        use_enum_values=True,
        arbitrary_types_allowed=False,
    )

    error_code: int = Field(ge=1000, le=9999, description="Numeric error code")
    error_message: str = Field(description="Human-readable error description")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional debugging context (original_message_id, affected_queue, etc)",
    )

    @field_validator("error_code")
    @classmethod
    def validate_error_code(cls, v: int) -> int:
        """Ensure error code is in valid range."""
        if not (1000 <= v <= 9999):
            raise ValueError("error_code must be between 1000 and 9999")
        return v
