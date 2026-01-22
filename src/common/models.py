"""SQLAlchemy ORM models for task state and execution tracking.

Provides:
- Task: Represents a user request and its execution state
- ExecutionLog: Step-by-step log of what agents did during task execution
"""

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
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

    # Audit columns (Phase 5)
    services_touched = Column(JSON, nullable=True)
    # Array of service names touched by this task (e.g., ["kuma", "portainer"])

    outcome = Column(JSON, nullable=True)
    # Execution outcome: {"success": bool, "output_summary": str, "error_type": str|null}

    suggestions = Column(JSON, nullable=True)
    # Post-mortem scaffolding: [{"suggestion": str, "reason": str, "created_at": str}]
    # Unpopulated in v1; v2 post-mortem agent will populate

    # Relationships
    execution_logs = relationship(
        "ExecutionLog",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    pause_queue_entries = relationship(
        "PauseQueueEntry",
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


class AgentRegistry(Base):
    """Agent registry model for tracking agent capabilities and status.

    Tracks:
    - Agent identity and type (infra, code, research, desktop)
    - Capabilities (what work types this agent can perform)
    - Specializations (expert areas like "config_specialist", "deployment_expert")
    - Online status and last heartbeat
    """

    __tablename__ = "agent_registry"

    # Primary key
    agent_id = Column(UUID(as_uuid=True), primary_key=True)

    # Agent identity
    agent_type = Column(String(50), nullable=False)
    # Values: infra|code|research|desktop

    pool_name = Column(String(100), nullable=False)
    # Pool identifier (e.g., "infra_pool_1", "code_pool_main")

    # Capabilities and specializations
    capabilities = Column(JSON, nullable=False)
    # List of work types this agent can handle (e.g., ["deploy_service", "run_playbook"])

    specializations = Column(JSON, nullable=True)
    # Optional list of expertise areas (e.g., ["config_specialist", "deployment_expert"])

    # Status tracking
    status = Column(String(50), nullable=False, default="offline")
    # Values: online|offline|busy

    last_heartbeat_at = Column(DateTime, nullable=True)
    # When agent last sent a heartbeat

    # Resource metrics from heartbeats
    resource_metrics = Column(JSON, nullable=False, default=dict)
    # Current resource metrics: {cpu_percent, cpu_cores_physical, cpu_cores_available,
    # cpu_load_1min, cpu_load_5min, memory_percent, memory_available_gb,
    # gpu_vram_total_gb, gpu_vram_available_gb, gpu_type}

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Relationships
    performance_records = relationship(
        "AgentPerformance",
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    routing_decisions = relationship(
        "RoutingDecision",
        back_populates="selected_agent",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return (
            f"<AgentRegistry(agent_id={self.agent_id}, agent_type={self.agent_type}, "
            f"pool_name={self.pool_name}, status={self.status})>"
        )


class AgentPerformance(Base):
    """Agent performance tracking model for success rates and execution history.

    Records:
    - Success and failure counts per work type
    - Execution duration metrics
    - Difficulty assessments from agents
    """

    __tablename__ = "agent_performance"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Foreign key to agent
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agent_registry.agent_id"), nullable=False)

    # Work type being tracked
    work_type = Column(String(100), nullable=False)
    # e.g., "deploy_service", "run_playbook", "add_config"

    # Success and failure tracking
    success_count = Column(Integer, nullable=False, default=0)
    failure_count = Column(Integer, nullable=False, default=0)

    # Duration metrics
    total_duration_ms = Column(Integer, nullable=False, default=0)
    # Sum of all execution times for this work type on this agent

    # Last execution
    last_execution_at = Column(DateTime, nullable=True)

    # Difficulty assessment from agent
    difficulty_assessment = Column(String(50), nullable=True)
    # Values: straightforward|tricky|failed

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Relationships
    agent = relationship("AgentRegistry", back_populates="performance_records")

    def __repr__(self):
        return (
            f"<AgentPerformance(agent_id={self.agent_id}, work_type={self.work_type}, "
            f"success={self.success_count}, failures={self.failure_count})>"
        )


class RoutingDecision(Base):
    """Routing decision audit trail for all agent routing decisions.

    Records:
    - Which agent was selected for a task
    - Why (success rate, specialization match, context, load)
    - Whether this was a retry attempt
    - Full audit trail for post-mortem analysis
    """

    __tablename__ = "routing_decisions"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Reference to task being routed
    task_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    # Work type being routed
    work_type = Column(String(100), nullable=False)

    # Agent pool and selection
    agent_pool = Column(String(100), nullable=False)
    # Pool name (e.g., "infra_pool_1")

    selected_agent_id = Column(UUID(as_uuid=True), ForeignKey("agent_registry.agent_id"), nullable=True)

    # Scoring factors
    success_rate_percent = Column(Integer, nullable=True)
    # Agent's success rate at this work type (0-100)

    specialization_match = Column(Integer, nullable=False, default=0)
    # Boolean (0 or 1): agent has specialization for this work type

    recent_context_match = Column(Integer, nullable=False, default=0)
    # Boolean (0 or 1): agent recently executed similar work

    # Retry tracking
    retried = Column(Integer, nullable=False, default=0)
    # Boolean (0 or 1): whether this was a retry attempt

    # Selection explanation
    reason = Column(String, nullable=True)
    # Human-readable explanation of why this agent was selected

    # Timestamp
    created_at = Column(DateTime, nullable=False, default=func.now(), index=True)

    # Relationships
    selected_agent = relationship("AgentRegistry", back_populates="routing_decisions")

    def __repr__(self):
        return (
            f"<RoutingDecision(id={self.id}, task_id={self.task_id}, "
            f"work_type={self.work_type}, agent_id={self.selected_agent_id}, "
            f"created_at={self.created_at})>"
        )


class PauseQueueEntry(Base):
    """Persisted pause queue entry for work awaiting resources.

    Used by PauseManager to persist paused work that survives orchestrator restart.
    Entries removed when work resumes or is cancelled.

    Attributes:
        id: Auto-incrementing primary key
        task_id: Foreign key to tasks table
        work_plan_json: Serialized WorkPlan as JSON
        reason: Why work was paused ('insufficient_capacity', 'manual_pause')
        paused_at: When work was paused
        resume_after: Optional datetime for timed auto-resume
        priority: Priority level for resume ordering (lower = higher priority)
    """

    __tablename__ = "pause_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.task_id"), nullable=False)
    work_plan_json = Column(JSON, nullable=False)
    reason = Column(String(100), nullable=False)
    paused_at = Column(DateTime, nullable=False, default=func.now())
    resume_after = Column(DateTime, nullable=True)
    priority = Column(Integer, nullable=False, default=3)

    # Relationship
    task = relationship("Task", back_populates="pause_queue_entries")

    def __repr__(self):
        return f"<PauseQueueEntry(id={self.id}, task_id={self.task_id}, reason={self.reason})>"


class PlaybookMapping(Base):
    """Playbook mapping model for semantic task-to-playbook cache.

    Tracks:
    - Task intent to playbook path mappings
    - Confidence scores for match quality
    - Embedding vectors for semantic similarity
    - Usage statistics for cache optimization
    """

    __tablename__ = "playbook_mappings"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Intent tracking
    intent = Column(String(500), nullable=False)
    # The original task intent text

    intent_hash = Column(String(64), nullable=False, unique=True)
    # SHA256 hash of normalized intent for fast lookup

    # Mapping result
    playbook_path = Column(String(500), nullable=False)
    # Path to the matched playbook

    confidence = Column(sa.Float, nullable=False)
    # Match confidence score (0.0-1.0)

    match_method = Column(String(50), nullable=False)
    # How match was found: 'exact', 'cached', 'semantic'

    embedding_vector = Column(JSON, nullable=True)
    # Embedding vector stored as JSON array for portability

    # Usage tracking
    created_at = Column(DateTime, nullable=False, default=func.now())
    last_used_at = Column(DateTime, nullable=False, default=func.now())
    use_count = Column(Integer, nullable=False, default=1)

    @staticmethod
    def normalize_intent(intent: str) -> str:
        """Normalize intent text for consistent hashing.

        Args:
            intent: Raw task intent text

        Returns:
            Normalized intent (lowercased, stripped whitespace)
        """
        return intent.lower().strip()

    def __repr__(self):
        return (
            f"<PlaybookMapping(id={self.id}, intent='{self.intent[:30]}...', "
            f"playbook_path={self.playbook_path}, confidence={self.confidence:.2f}, "
            f"method={self.match_method})>"
        )


class PlaybookCache(Base):
    """Playbook cache model for storing playbook metadata.

    Tracks:
    - Playbook file paths and service names
    - Metadata (description, required vars, tags)
    - File hash for cache invalidation
    - Discovery and update timestamps
    """

    __tablename__ = "playbook_cache"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Playbook identification
    playbook_path = Column(String(500), nullable=False, unique=True)
    # Full path to playbook file

    service_name = Column(String(100), nullable=True, index=True)
    # Service name extracted from playbook (e.g., "kuma", "portainer")

    # Metadata
    description = Column(String, nullable=True)
    # Human-readable description from playbook header or play name

    required_vars = Column(JSON, nullable=False, server_default="[]")
    # Required variables as JSON array

    tags = Column(JSON, nullable=False, server_default="[]")
    # Tags as JSON array for categorization

    file_hash = Column(String(64), nullable=False)
    # SHA256 hash of playbook file for invalidation

    # Timestamps
    discovered_at = Column(DateTime, nullable=False, default=func.now())
    # When playbook was first discovered

    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    # Last update timestamp

    def __repr__(self):
        return (
            f"<PlaybookCache(id={self.id}, service_name={self.service_name}, "
            f"playbook_path={self.playbook_path})>"
        )


class PlaybookSuggestion(Base):
    """Playbook improvement suggestion from ansible-lint analysis.

    Stores suggestions generated by PlaybookAnalyzer after playbook failures.
    Suggestions categorized by type (idempotency, error_handling, etc.) with
    reasoning to help improve playbook quality.

    Category choices: idempotency, error_handling, performance, best_practices, standards
    Severity choices: error, warning, info
    Status choices: pending, applied, dismissed
    """

    __tablename__ = "playbook_suggestions"

    # Choices constants
    CATEGORY_CHOICES = ['idempotency', 'error_handling', 'performance', 'best_practices', 'standards']
    SEVERITY_CHOICES = ['error', 'warning', 'info']
    STATUS_CHOICES = ['pending', 'applied', 'dismissed']

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Playbook identification
    playbook_path = Column(String(500), nullable=False, index=True)
    # Path to playbook that needs improvement

    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.task_id", ondelete="SET NULL"), nullable=True)
    # FK to tasks if suggestion from execution

    # Categorization
    category = Column(String(50), nullable=False, index=True)
    # One of: idempotency, error_handling, performance, best_practices, standards

    rule_id = Column(String(100), nullable=False)
    # ansible-lint rule ID (e.g., "no-changed-when", "command-instead-of-module")

    # Suggestion details
    message = Column(sa.Text, nullable=False)
    # Lint message from ansible-lint

    reasoning = Column(sa.Text, nullable=True)
    # Human-readable explanation of why this matters

    line_number = Column(Integer, nullable=True)
    # Line number in playbook where issue found

    severity = Column(String(20), nullable=False, index=True)
    # One of: error, warning, info

    # Status tracking
    status = Column(String(20), nullable=False, default='pending', index=True)
    # One of: pending, applied, dismissed

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    resolved_at = Column(DateTime, nullable=True)

    # Relationship
    task = relationship("Task", backref="playbook_suggestions")

    def __repr__(self):
        return (
            f"<PlaybookSuggestion(id={self.id}, category={self.category}, "
            f"rule_id={self.rule_id}, severity={self.severity}, status={self.status})>"
        )


# Pydantic models for request parsing and decomposition
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


class FallbackDecision(BaseModel):
    """Tracks the fallback decision for external AI routing with quota awareness.

    Records:
    - Which LLM (Claude or Ollama) was selected for a task
    - Why the decision was made (quota critical, high complexity, etc)
    - Resource status at decision time (quota remaining)
    - Actual model used and cost tracking for audits

    Attributes:
        task_id: UUID of the task this decision applies to
        decision: Selected action ("use_claude"|"use_ollama"|"no_fallback")
        reason: Why decision was made ("quota_critical"|"high_complexity"|"local_sufficient"|"claude_failed")
        quota_remaining_percent: Remaining budget fraction (0.0-1.0) at decision time
        complexity_level: Task complexity assessment ("simple"|"medium"|"complex")
        fallback_tier: Which fallback tier was used (0=primary Claude, 1=fallback Ollama, 2=failure)
        model_used: Which LLM was actually used ("claude-opus-4.5"|"ollama/neural-chat")
        tokens_used: Token count if available from LLM response
        cost_usd: Estimated cost if available from LLM
        error_message: Error description if fallback occurred
        created_at: When decision was made
    """
    task_id: str = Field(..., description="UUID of task this decision applies to")
    decision: str = Field(
        ...,
        pattern="^(use_claude|use_ollama|no_fallback)$",
        description="Selected action: use_claude, use_ollama, or no_fallback"
    )
    reason: str = Field(
        ...,
        pattern="^(quota_critical|high_complexity|local_sufficient|claude_failed)$",
        description="Why this decision was made"
    )
    quota_remaining_percent: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Quota remaining (0.0-1.0) at decision time"
    )
    complexity_level: str = Field(
        ...,
        pattern="^(simple|medium|complex)$",
        description="Task complexity: simple, medium, or complex"
    )
    fallback_tier: int = Field(
        ...,
        ge=0,
        le=2,
        description="Fallback tier used: 0=primary Claude, 1=fallback Ollama, 2=failure"
    )
    model_used: str = Field(
        ...,
        description="LLM model used (claude-opus-4.5, ollama/neural-chat, etc)"
    )
    tokens_used: Optional[int] = Field(
        default=None,
        ge=0,
        description="Token count if available"
    )
    cost_usd: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Estimated cost in USD if available"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if fallback occurred"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When decision was made"
    )


class PauseQueueEntryModel(BaseModel):
    """Pydantic model for pause queue entry serialization.

    Used for API responses and inter-service communication. Maps to PauseQueueEntry ORM.

    Attributes:
        id: Auto-generated primary key (None for new entries)
        task_id: UUID of the paused task
        work_plan: Serialized WorkPlan object
        reason: Why work was paused ('insufficient_capacity', 'manual_pause')
        paused_at: When work was paused
        resume_after: Optional datetime for timed auto-resume
        priority: Priority level for resume ordering (default 3)
    """
    id: Optional[int] = Field(default=None, description="Auto-generated ID (None for new entries)")
    task_id: str = Field(..., description="UUID of the paused task")
    work_plan: WorkPlan = Field(..., description="The paused work plan")
    reason: str = Field(
        ...,
        pattern="^(insufficient_capacity|manual_pause)$",
        description="Why work was paused"
    )
    paused_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When work was paused"
    )
    resume_after: Optional[datetime] = Field(
        default=None,
        description="Optional datetime for timed auto-resume"
    )
    priority: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Priority level (1=highest, 5=lowest)"
    )
