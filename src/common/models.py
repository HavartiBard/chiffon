"""SQLAlchemy ORM models for task state and execution tracking.

Provides:
- Task: Represents a user request and its execution state
- ExecutionLog: Step-by-step log of what agents did during task execution
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, UUID, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from .database import Base


class Task(Base):
    """Task model representing a user request and its execution state.

    Tracks:
    - Request details (what user asked for)
    - Status transitions (pending -> approved -> executing -> completed/failed)
    - Resource tracking (estimated vs actual)
    - External AI costs
    - Error information
    """

    __tablename__ = "tasks"

    # Primary key
    task_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # Request details
    project_id = Column(UUID(as_uuid=True), nullable=True)
    request_text = Column(String, nullable=False)
    created_by = Column(String(255), nullable=True)

    # Status tracking
    status = Column(
        String(50),
        nullable=False,
        default="pending",
    )
    # Status values: pending|approved|executing|completed|failed|rejected

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now(), index=True)
    approved_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Resource tracking
    estimated_resources = Column(JSON, nullable=True)
    # Expected format: {duration_seconds: int, gpu_vram_mb: int, cpu_cores: int}

    actual_resources = Column(JSON, nullable=True)
    # Actual format: {duration_seconds: int, gpu_vram_mb_used: int, cpu_time_ms: int}

    # External AI tracking
    external_ai_used = Column(JSON, nullable=True)
    # Format: {model: str, token_count: int, cost_usd: float}

    # Error tracking
    error_message = Column(String, nullable=True)

    # Relationships
    execution_logs = relationship(
        "ExecutionLog",
        back_populates="task",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return (
            f"<Task(task_id={self.task_id}, status={self.status}, "
            f"request={self.request_text[:50]}...)>"
        )


class ExecutionLog(Base):
    """Execution log model for tracking agent actions during task execution.

    Records:
    - What each agent did (step_number, agent_type, action)
    - Step status and duration
    - Output and errors
    """

    __tablename__ = "execution_logs"

    # Primary key
    log_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # Foreign key to task
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.task_id"), nullable=False, index=True)

    # Step tracking
    step_number = Column(Integer, nullable=False)
    agent_type = Column(String(50), nullable=False)
    # Agent types: orchestrator|infra|desktop|code|research

    # Action details
    action = Column(String, nullable=False)

    # Status and timing
    status = Column(String(50), nullable=False)
    # Status values: running|completed|failed

    duration_ms = Column(Integer, nullable=True)

    # Output tracking
    output_summary = Column(String, nullable=True)
    # First 500 chars of output for easy viewing
    output_full = Column(JSON, nullable=True)
    # Full output or reference to where it's stored

    # Timestamp
    timestamp = Column(DateTime, nullable=False, default=func.now())

    # Relationships
    task = relationship("Task", back_populates="execution_logs")

    def __repr__(self):
        return (
            f"<ExecutionLog(log_id={self.log_id}, task_id={self.task_id}, "
            f"step={self.step_number}, agent={self.agent_type}, status={self.status})>"
        )


# Pydantic models for request parsing and decomposition
from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional


class Subtask(BaseModel):
    """Represents a single decomposed task from a user request.

    Attributes:
        order: Task sequence number (1-based)
        name: Human-readable task name
        intent: Recognized work type (e.g., "deploy_kuma", "add_config")
        confidence: Confidence in this decomposition (0.0-1.0)
        parameters: Optional task-specific parameters
    """
    order: int = Field(..., description="Task sequence, 1-based")
    name: str = Field(..., description="Human-readable task name")
    intent: str = Field(..., description="Recognized work type for routing")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Decomposition confidence")
    parameters: Optional[Dict[str, Any]] = Field(default=None, description="Task-specific parameters")


class DecomposedRequest(BaseModel):
    """Result of decomposing a natural language request into structured work.

    Attributes:
        request_id: Unique identifier assigned by orchestrator
        original_request: Full user input text
        subtasks: List of decomposed executable tasks
        ambiguities: List of unclear/ambiguous aspects (empty if none)
        out_of_scope: List of capabilities not available (empty if all in scope)
        complexity_level: Assessment of request complexity
        decomposer_model: Which LLM performed the decomposition
    """
    request_id: str = Field(..., description="UUID assigned by orchestrator")
    original_request: str = Field(..., description="Full user input")
    subtasks: List[Subtask] = Field(default_factory=list, description="Decomposed tasks")
    ambiguities: List[str] = Field(default_factory=list, description="Ambiguous aspects")
    out_of_scope: List[str] = Field(default_factory=list, description="Out-of-scope items")
    complexity_level: str = Field(..., description="simple|medium|complex")
    decomposer_model: str = Field(..., description="Model used: claude|ollama")


class RequestParsingConfig(BaseModel):
    """Configuration for natural language understanding behavior.

    Attributes:
        min_confidence_threshold: Confidence below this triggers ambiguity flag
        max_subtasks: Maximum subtasks per request
        use_claude_for_complex: Use Claude for complex requests vs Ollama
        log_out_of_scope: Log out-of-scope requests to database
    """
    min_confidence_threshold: float = Field(
        default=0.60,
        ge=0.0,
        le=1.0,
        description="Below this, task flagged as ambiguous"
    )
    max_subtasks: int = Field(default=10, ge=1, description="Max subtasks per request")
    use_claude_for_complex: bool = Field(
        default=True,
        description="Use Claude for complex requests vs Ollama"
    )
    log_out_of_scope: bool = Field(
        default=True,
        description="Log out-of-scope requests to DB"
    )


class WorkTask(BaseModel):
    """Single executable task in a work plan.

    Represents a concrete, actionable unit of work with resource requirements,
    dependencies, and fallback options.

    Attributes:
        order: Sequence number in the plan (1-based)
        name: Human-readable task name
        work_type: Type of work (e.g., "deploy_service", "run_playbook")
        agent_type: Target agent type (infra, code, research, desktop)
        parameters: Task-specific parameters as key-value dict
        resource_requirements: Dict with estimated_duration_seconds, gpu_vram_mb, cpu_cores
        depends_on: List of task orders this task depends on (empty if no dependencies)
        alternatives: List of alternative approaches if resources unavailable
        estimated_external_ai_calls: Estimated number of Claude API calls needed
    """
    order: int = Field(..., ge=1, description="Task sequence number, 1-based")
    name: str = Field(..., description="Human-readable task name")
    work_type: str = Field(..., description="Type of work to execute")
    agent_type: str = Field(
        ...,
        pattern="^(infra|code|research|desktop)$",
        description="Target agent type"
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Task-specific parameters"
    )
    resource_requirements: Dict[str, int] = Field(
        ...,
        description="Resource requirements with estimated_duration_seconds, gpu_vram_mb, cpu_cores"
    )
    depends_on: List[int] = Field(
        default_factory=list,
        description="Task orders this task depends on"
    )
    alternatives: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Alternative approaches if primary resources unavailable"
    )
    estimated_external_ai_calls: int = Field(
        default=0,
        ge=0,
        description="Estimated number of Claude API calls needed"
    )


class WorkPlan(BaseModel):
    """Complete execution plan with ordered tasks and resource awareness.

    Represents a human-approved plan ready for execution, derived from a
    DecomposedRequest with resource-aware task ordering and fallback strategies.

    Attributes:
        plan_id: Unique identifier for this plan
        request_id: UUID linking back to original user request
        tasks: Ordered list of executable tasks
        estimated_duration_seconds: Total estimated execution time
        complexity_level: Assessment of plan complexity (simple|medium|complex)
        will_use_external_ai: True if any task requires Claude fallback
        status: Current plan status (pending_approval|approved|executing|completed|rejected)
        created_at: When plan was generated
        approved_at: When user approved (if applicable)
        human_readable_summary: Plain text summary for user review
    """
    plan_id: str = Field(..., description="Unique plan identifier (UUID)")
    request_id: str = Field(..., description="UUID of original request")
    tasks: List[WorkTask] = Field(..., description="Ordered execution tasks")
    estimated_duration_seconds: int = Field(
        ...,
        ge=0,
        description="Total estimated execution time in seconds"
    )
    complexity_level: str = Field(
        ...,
        pattern="^(simple|medium|complex)$",
        description="Plan complexity assessment"
    )
    will_use_external_ai: bool = Field(
        default=False,
        description="True if any task requires Claude fallback"
    )
    status: str = Field(
        default="pending_approval",
        pattern="^(pending_approval|approved|executing|completed|rejected)$",
        description="Current plan status"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When plan was generated"
    )
    approved_at: Optional[datetime] = Field(
        default=None,
        description="When user approved the plan"
    )
    human_readable_summary: str = Field(
        ...,
        description="Plain text summary of plan for user review"
    )


class IntentToWorkTypeMapping(BaseModel):
    """Configuration mapping decomposed intents to executable work types.

    Used by WorkPlanner to translate high-level intents from RequestDecomposer
    into concrete work_type assignments with resource estimates and alternatives.

    Attributes:
        intent: Intent from RequestDecomposer (e.g., "deploy_kuma")
        work_type: Executable work type (e.g., "deploy_service")
        agent_type: Target agent pool (infra|code|research|desktop)
        estimated_duration_seconds: Estimated execution time
        gpu_vram_mb: Required GPU VRAM in MB
        cpu_cores: Required CPU cores
        alternatives: List of alternative approaches with different resources
    """
    intent: str = Field(..., description="Intent from decomposer")
    work_type: str = Field(..., description="Mapped work type")
    agent_type: str = Field(
        ...,
        pattern="^(infra|code|research|desktop)$",
        description="Target agent type"
    )
    estimated_duration_seconds: int = Field(
        ...,
        ge=0,
        description="Estimated execution time"
    )
    gpu_vram_mb: int = Field(
        default=0,
        ge=0,
        description="Required GPU VRAM in MB"
    )
    cpu_cores: int = Field(
        default=1,
        ge=1,
        description="Required CPU cores"
    )
    alternatives: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Alternative approaches with different resource requirements"
    )
