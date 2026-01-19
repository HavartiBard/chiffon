"""SQLAlchemy ORM models for task state and execution tracking.

Provides:
- Task: Represents a user request and its execution state
- ExecutionLog: Step-by-step log of what agents did during task execution
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, Integer, DateTime, JSON, UUID, Enum, ForeignKey, func
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
