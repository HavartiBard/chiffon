"""OrchestratorService: Central business logic for task dispatch and agent management.

Provides:
- Task dispatch to agents via RabbitMQ
- Task status queries
- Agent registration and health tracking
- Work result handling with deduplication
- Task cancellation
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID, uuid4

import aio_pika
from sqlalchemy.orm import Session

from src.common.config import Config
from src.common.models import (
    Task,
    DecomposedRequest,
    WorkPlan,
    FallbackDecision,
    AgentRegistry,
)
from src.common.protocol import (
    MessageEnvelope,
    StatusUpdate,
    WorkRequest,
    WorkResult,
)
from src.common.rabbitmq import declare_queues, get_connection_string
from src.orchestrator.nlu import RequestDecomposer
from src.orchestrator.planner import WorkPlanner
from src.orchestrator.router import AgentRouter
from src.orchestrator.fallback import ExternalAIFallback
from src.orchestrator.pause_manager import PauseManager
from src.orchestrator.git_service import GitService, GitServiceError
from src.common.litellm_client import LiteLLMClient

logger = logging.getLogger(__name__)


class RequestCache:
    """Simple LRU cache for request idempotency.

    Stores (request_id -> result) pairs with TTL-based expiration.
    Used to prevent duplicate work execution when messages are redelivered.
    """

    def __init__(self, ttl_seconds: int = 300, max_size: int = 10000):
        """Initialize cache with TTL and max size limits.

        Args:
            ttl_seconds: Time-to-live for cached entries (default 300 seconds = 5 minutes)
            max_size: Maximum cache size; evicts oldest entry if exceeded
        """
        self.ttl = ttl_seconds
        self.max_size = max_size
        self.cache: dict[str, tuple[dict, float]] = {}  # request_id -> (result, timestamp)
        self.logger = logging.getLogger("orchestrator.cache")

    def get(self, request_id: str) -> Optional[dict]:
        """Retrieve cached result if exists and not expired.

        Args:
            request_id: The request ID to look up

        Returns:
            Cached result dict if found and not expired, None otherwise
        """
        if request_id in self.cache:
            result, ts = self.cache[request_id]
            if time.time() - ts < self.ttl:
                self.logger.debug(f"Cache hit for request_id={request_id}")
                return result
            else:
                # Expired; remove and return None
                del self.cache[request_id]
                self.logger.debug(f"Cache expired for request_id={request_id}")
        return None

    def set(self, request_id: str, result: dict) -> None:
        """Store result with timestamp.

        Args:
            request_id: The request ID to cache
            result: The result data to cache
        """
        if len(self.cache) >= self.max_size:
            # Evict oldest entry
            oldest_id = next(iter(self.cache))
            del self.cache[oldest_id]
            self.logger.warning(f"Cache full; evicted oldest entry {oldest_id}")

        self.cache[request_id] = (result, time.time())
        self.logger.debug(f"Cached result for request_id={request_id}")

    def cleanup(self) -> None:
        """Periodically remove expired entries."""
        now = time.time()
        expired = [rid for rid, (_, ts) in self.cache.items() if now - ts >= self.ttl]
        for rid in expired:
            del self.cache[rid]
        if expired:
            self.logger.debug(f"Cleanup: removed {len(expired)} expired entries")


class OrchestratorService:
    """Core orchestrator service managing task dispatch and agent lifecycle.

    Responsibilities:
    - Publishing work requests to RabbitMQ (with priority)
    - Tracking task status in PostgreSQL
    - Managing agent registry (registrations, heartbeats, offline detection)
    - Handling work results and broadcasting via WebSocket
    - Canceling in-flight tasks
    """

    def __init__(
        self,
        config: Config,
        db_session: Session,
        litellm_client: Optional[LiteLLMClient] = None,
        repo_path: str = ".",
    ):
        """Initialize orchestrator service.

        Args:
            config: Configuration object
            db_session: SQLAlchemy session for database operations
            litellm_client: Optional LiteLLMClient for request decomposition and fallback
            repo_path: Path to git repository for audit trail (default: "." = project root)
        """
        self.config = config
        self.db = db_session
        self.connection: Optional[aio_pika.Connection] = None
        self.channel: Optional[aio_pika.Channel] = None
        self.request_cache = RequestCache(ttl_seconds=300)  # 5-minute cache
        self.logger = logging.getLogger("orchestrator.service")
        self.ws_manager: Optional[object] = None  # Set by main.py for WebSocket broadcasting

        # Initialize orchestration components (Phase 3 modules)
        self.litellm = litellm_client
        self.decomposer: Optional[RequestDecomposer] = None
        self.planner: Optional[WorkPlanner] = None
        self.router: Optional[AgentRouter] = None
        self.fallback: Optional[ExternalAIFallback] = None

        # Initialize GitService for audit trail (Phase 5)
        try:
            git_repo_path = repo_path or "."
            self.git_service = GitService(repo_path=git_repo_path)
            self.logger.info(f"Git audit trail enabled, repo: {git_repo_path}")
        except GitServiceError as e:
            self.logger.warning(f"Git audit trail initialization failed: {e}")
            self.git_service = None

        # Store for request → plan mappings (request_id → plan)
        self._request_plans: dict[str, WorkPlan] = {}  # Simple in-memory store, would use DB in production
        # Store for request → decomposed_request mappings (request_id → decomposed_request)
        self._decomposed_requests: dict[str, DecomposedRequest] = {}  # Simple in-memory store

    async def connect(self) -> None:
        """Initialize RabbitMQ connection and declare queue topology.

        Establishes connection, creates channel, and ensures all queues exist.
        Raises on connection failure.
        """
        try:
            self.logger.info("Connecting to RabbitMQ")
            connection = await aio_pika.connect_robust(get_connection_string())
            self.connection = connection  # type: ignore
            channel = await connection.channel()
            self.channel = channel  # type: ignore

            self.logger.info("Declaring queue topology")
            await declare_queues(channel)

            self.logger.info("RabbitMQ connection established")
        except Exception as e:
            self.logger.error(f"Failed to connect to RabbitMQ: {e}", exc_info=True)
            raise

    async def disconnect(self) -> None:
        """Gracefully close RabbitMQ connection and channel.

        Safe to call even if not connected.
        """
        try:
            if self.channel:
                await self.channel.close()
                self.logger.info("Channel closed")
            if self.connection:
                await self.connection.close()
                self.logger.info("Connection closed")
        except Exception as e:
            self.logger.error(f"Error during disconnect: {e}", exc_info=True)

    def _determine_agent_type(self, work_type: str) -> str:
        """Map work_type to target agent_type.

        Args:
            work_type: Type of work (e.g., "ansible", "docker", "metrics")

        Returns:
            Agent type ("infra", "desktop", "code", "research")

        Raises:
            ValueError: If work_type has no mapping
        """
        # Mapping based on work type
        mapping = {
            "ansible": "infra",
            "docker": "infra",
            "shell_script": "infra",
            "deploy_service": "infra",
            "run_playbook": "infra",
            "metrics": "desktop",
            "gpu_status": "desktop",
            "resource_check": "desktop",
            "code_gen": "code",
            "code_review": "code",
            "research": "research",
            # Test work types for integration testing
            "test": "infra",
            "echo": "infra",
            "slow_echo": "infra",
            "fail": "infra",
        }

        if work_type in mapping:
            return mapping[work_type]
        else:
            raise ValueError(
                f"Unknown work_type: {work_type}. "
                f"Valid types: {', '.join(mapping.keys())}"
            )

    async def dispatch_work(
        self,
        task_id: UUID,
        work_type: str,
        parameters: dict,
        priority: int = 3,
    ) -> dict:
        """Dispatch work request to agents via RabbitMQ.

        Creates a work request, publishes to RabbitMQ, stores task in DB.

        Args:
            task_id: Unique task identifier
            work_type: Type of work to perform
            parameters: Work-specific parameters
            priority: Priority level 1-5 (1=background, 5=critical)

        Returns:
            dict with trace_id, request_id, task_id, status

        Raises:
            ValueError: If priority out of range or agent_type unknown
        """
        # Validate priority
        if not (1 <= priority <= 5):
            raise ValueError(f"Priority must be 1-5, got {priority}")

        # Determine target agent
        try:
            agent_type = self._determine_agent_type(work_type)
        except ValueError as e:
            self.logger.error(f"Invalid work_type: {e}")
            raise

        # Generate IDs
        request_id = uuid4()
        trace_id = uuid4()

        # Create work request
        work_req = WorkRequest(
            task_id=task_id,
            work_type=work_type,
            parameters=parameters or {},
            hints={},
        )

        # Wrap in message envelope
        envelope = MessageEnvelope(
            from_agent="orchestrator",
            to_agent=agent_type,
            type="work_request",
            priority=priority,
            trace_id=trace_id,
            request_id=request_id,
            payload=work_req.model_dump(),
        )

        # Publish to RabbitMQ
        try:
            if not self.channel:
                raise RuntimeError("RabbitMQ channel not connected")

            # Use persistent delivery for high/critical priority (4-5)
            # Use non-persistent for lower priorities (1-3) for speed
            is_persistent = priority >= 4
            message = aio_pika.Message(
                body=envelope.to_json().encode(),
                priority=priority,
                delivery_mode=(
                    aio_pika.DeliveryMode.PERSISTENT
                    if is_persistent
                    else aio_pika.DeliveryMode.NOT_PERSISTENT
                ),
            )

            await self.channel.default_exchange.publish(message, routing_key="work_queue")
            self.logger.info(
                "Work dispatched",
                extra={
                    "trace_id": str(trace_id),
                    "request_id": str(request_id),
                    "task_id": str(task_id),
                    "work_type": work_type,
                    "priority": priority,
                },
            )
        except Exception as e:
            self.logger.error(
                f"Failed to publish work request: {e}",
                extra={"trace_id": str(trace_id), "task_id": str(task_id)},
            )
            raise

        # Store task in database
        try:
            task = Task(
                task_id=task_id,
                request_text=f"{work_type}: {json.dumps(parameters)[:100]}",
                status="pending",
            )
            self.db.add(task)
            self.db.commit()
            self.logger.info(
                "Task stored in DB",
                extra={"trace_id": str(trace_id), "task_id": str(task_id)},
            )
        except Exception as e:
            self.logger.error(
                f"Failed to store task in DB: {e}",
                extra={"trace_id": str(trace_id), "task_id": str(task_id)},
            )
            self.db.rollback()
            raise

        return {
            "trace_id": str(trace_id),
            "request_id": str(request_id),
            "task_id": str(task_id),
            "status": "pending",
        }

    async def get_task_status(self, task_id: UUID) -> dict:
        """Query task status from database.

        Args:
            task_id: Task to query

        Returns:
            dict with task_id, status, progress, output, error_message, result, trace_id

        Raises:
            ValueError: If task not found
        """
        try:
            task = self.db.query(Task).filter(Task.task_id == task_id).first()
            if not task:
                raise ValueError(f"Task not found: {task_id}")

            return {
                "task_id": str(task.task_id),
                "status": task.status,
                "progress": "",  # TODO: compute from execution logs
                "output": "",  # TODO: aggregate from execution logs
                "error_message": task.error_message,
                "result": None,  # TODO: aggregate actual_resources
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.completed_at.isoformat()
                if task.completed_at
                else None,
            }
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(f"Error querying task status: {e}", exc_info=True)
            raise

    async def register_agent(
        self,
        agent_id: UUID,
        agent_type: str,
        status: str,
        resources: dict,
    ) -> None:
        """Register agent heartbeat (for agent lifecycle tracking).

        In Phase 2, we store this in-memory. Phase 3+ will use database.

        Args:
            agent_id: Agent identifier
            agent_type: Type of agent (infra, desktop, etc.)
            status: Agent status (online, offline, busy)
            resources: Resource metrics dict
        """
        self.logger.info(
            "Agent registered",
            extra={
                "agent_id": str(agent_id),
                "agent_type": agent_type,
                "status": status,
                "resources": resources,
            },
        )
        # TODO: Store in database for persistence and querying

    async def list_agents(
        self,
        agent_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[dict]:
        """List connected agents with resource status.

        Args:
            agent_type: Filter by agent type (optional)
            status: Filter by status (online/offline/busy) (optional)

        Returns:
            List of agent dicts with id, type, status, resources, last_heartbeat_at
        """
        # TODO: Implement in-memory or DB-backed agent registry
        self.logger.info(f"Listing agents (type={agent_type}, status={status})")
        return []

    async def is_agent_online(self, agent_id: UUID) -> bool:
        """Check if agent is currently online based on recent heartbeat.

        Args:
            agent_id: Agent to check

        Returns:
            True if agent sent heartbeat within last 180 seconds, False otherwise
        """
        # TODO: Implement based on agent registry
        self.logger.debug(f"Checking agent online: {agent_id}")
        return False

    async def cancel_task(self, task_id: UUID) -> dict:
        """Cancel an in-flight task.

        Publishes cancellation message and updates task status.

        Args:
            task_id: Task to cancel

        Returns:
            dict with task_id and status='cancelled'

        Raises:
            ValueError: If task not in cancellable state
        """
        try:
            # Query task
            task = self.db.query(Task).filter(Task.task_id == task_id).first()
            if not task:
                raise ValueError(f"Task not found: {task_id}")

            # Check if cancellable
            if task.status not in ["pending", "executing"]:
                raise ValueError(
                    f"Cannot cancel task in status '{task.status}'. "
                    f"Only pending/executing tasks can be cancelled."
                )

            # Publish cancellation message (simplified; would need to track agent)
            # TODO: Publish to correct agent queue

            # Update task status
            task.status = "cancelled"
            task.completed_at = datetime.utcnow()
            self.db.commit()

            self.logger.info(f"Task cancelled: {task_id}")
            return {"task_id": str(task_id), "status": "cancelled"}
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(f"Error cancelling task: {e}", exc_info=True)
            self.db.rollback()
            raise

    async def handle_work_result(self, work_result: WorkResult, trace_id: UUID) -> None:
        """Handle work result from agent.

        Deduplicates based on request_id, stores result in DB, broadcasts via WebSocket.

        Args:
            work_result: WorkResult message from agent
            trace_id: Trace ID for correlation
        """
        try:
            # Check idempotency cache
            cache_key = str(work_result.task_id)  # Simplified; should use request_id
            cached = self.request_cache.get(cache_key)
            if cached:
                self.logger.info(
                    "Duplicate result (cached)",
                    extra={"trace_id": str(trace_id), "task_id": str(work_result.task_id)},
                )
                return

            # Query task
            task = self.db.query(Task).filter(Task.task_id == work_result.task_id).first()
            if not task:
                self.logger.warning(f"Result for unknown task: {work_result.task_id}")
                return

            # Update task - note: actual_resources is JSON, so assign as dict
            task.status = work_result.status  # type: ignore
            task.error_message = work_result.error_message  # type: ignore
            task.completed_at = datetime.utcnow()  # type: ignore
            task.actual_resources = {  # type: ignore
                "duration_ms": work_result.duration_ms,
                "exit_code": work_result.exit_code,
            }
            self.db.commit()

            # Commit outcome to git audit trail
            if self.git_service:
                try:
                    await self.git_service.commit_task_outcome(task)
                except Exception as e:
                    self.logger.error(f"Git audit commit failed for task {task.task_id}: {e}")
                    # Continue execution - git failure should not block orchestrator

            # Cache result
            self.request_cache.set(cache_key, work_result.model_dump())

            # Broadcast to WebSocket subscribers
            if self.ws_manager:
                await self.ws_manager.broadcast(
                    str(trace_id), work_result.model_dump(mode="json")
                )

            self.logger.info(
                "Work result handled",
                extra={
                    "trace_id": str(trace_id),
                    "task_id": str(work_result.task_id),
                    "status": work_result.status,
                },
            )
        except Exception as e:
            self.logger.error(
                f"Error handling work result: {e}",
                extra={"trace_id": str(trace_id), "task_id": str(work_result.task_id)},
                exc_info=True,
            )

    async def handle_agent_heartbeat(
        self, heartbeat: StatusUpdate, db: Session
    ) -> None:
        """Handle agent heartbeat and persist resource metrics to database.

        Receives heartbeat from agent with current resource metrics.
        Auto-registers new agents on first heartbeat. Updates existing agent
        registry with latest metrics and marks agent online.

        Args:
            heartbeat: StatusUpdate message from agent with resource metrics
            db: SQLAlchemy session for database operations

        Raises:
            Exception: If database commit fails (logged but not raised to protect orchestrator)
        """
        try:
            # Extract agent_id from heartbeat
            agent_id = heartbeat.agent_id
            agent_type = heartbeat.agent_type

            # Look up agent in registry
            agent = db.query(AgentRegistry).filter(
                AgentRegistry.agent_id == agent_id
            ).first()

            # Auto-register new agent
            if not agent:
                self.logger.info(f"Auto-registering new agent {agent_id} (type={agent_type})")
                agent = AgentRegistry(
                    agent_id=agent_id,
                    agent_type=agent_type,
                    status="online",
                    last_heartbeat_at=datetime.utcnow(),
                    pool_name=f"{agent_type}_pool_1",
                    capabilities=[],
                    specializations=[],
                    resource_metrics=heartbeat.resources,
                )
                db.add(agent)
            else:
                # Update existing agent
                agent.status = "online"
                agent.last_heartbeat_at = datetime.utcnow()
                agent.resource_metrics = heartbeat.resources

            # Commit to database
            try:
                db.commit()
                self.logger.info(
                    f"Heartbeat: agent={agent_id}, "
                    f"gpu_vram={heartbeat.resources.get('gpu_vram_available_gb', 0):.1f}GB, "
                    f"cpu_load={heartbeat.resources.get('cpu_load_1min', 0):.1f}",
                    extra={"agent_id": str(agent_id), "resources": heartbeat.resources},
                )
            except Exception as commit_err:
                self.logger.warning(f"Failed to commit heartbeat to DB: {commit_err}")
                db.rollback()

        except Exception as e:
            self.logger.error(f"Error handling agent heartbeat: {e}", exc_info=True)

    async def mark_agents_offline_periodically(self) -> None:
        """Background task to mark offline agents.

        Periodically queries agents with no heartbeat for >90s (3x heartbeat interval)
        and marks them offline. Runs every 30 seconds.

        Should be called as asyncio.create_task() during orchestrator startup.
        """
        timeout_seconds = self.config.heartbeat_timeout_seconds
        check_interval_seconds = 30  # Check every 30 seconds

        try:
            while True:
                try:
                    await asyncio.sleep(check_interval_seconds)

                    # Query agents offline > timeout
                    timeout_threshold = datetime.utcnow() - timedelta(seconds=timeout_seconds)
                    # Approximate: if last_heartbeat_at is None or far in past
                    offline_agents = self.db.query(AgentRegistry).filter(
                        (AgentRegistry.last_heartbeat_at == None) |
                        (AgentRegistry.last_heartbeat_at < timeout_threshold)
                    ).filter(AgentRegistry.status != "offline").all()

                    # Mark offline
                    for agent in offline_agents:
                        self.logger.info(
                            f"Marking agent offline: {agent.agent_id} "
                            f"(last heartbeat {timeout_seconds}+ seconds ago)"
                        )
                        agent.status = "offline"

                    if offline_agents:
                        self.db.commit()

                except asyncio.CancelledError:
                    self.logger.info("Offline detection task cancelled")
                    break
                except Exception as e:
                    self.logger.error(f"Error in offline detection: {e}", exc_info=True)
                    self.db.rollback()

        except asyncio.CancelledError:
            self.logger.info("Offline detection task stopped")
        except Exception as e:
            self.logger.error(f"Fatal error in offline detection: {e}", exc_info=True)

    # ==================== Phase 3: Orchestration Workflow ====================

    async def submit_request(self, request_text: str, user_id: str) -> dict:
        """Submit a natural language request for orchestration.

        Args:
            request_text: User's natural language request
            user_id: User ID submitting the request

        Returns:
            dict with request_id, status, and decomposed_request if successful

        Raises:
            ValueError: If request is invalid
        """
        try:
            # Validate request
            if not request_text or not isinstance(request_text, str):
                raise ValueError("Request cannot be empty")
            if len(request_text) > 10000:
                raise ValueError("Request too long (max 10000 chars)")

            # Generate request ID
            request_id = str(uuid4())
            self.logger.info(f"Submitting request {request_id}: {request_text[:100]}...")

            # Create task record
            try:
                task = Task(
                    task_id=uuid4(),
                    request_text=request_text,
                    status="pending",
                    created_by=user_id,
                )
                self.db.add(task)
                self.db.commit()
            except Exception as db_err:
                self.logger.warning(f"Failed to store request in DB: {db_err}")
                self.db.rollback()

            # Decompose request
            if not self.decomposer:
                raise ValueError("RequestDecomposer not initialized")

            try:
                decomposed = await self.decomposer.decompose(request_text)
                self.logger.info(
                    f"Decomposed request {request_id} into {len(decomposed.subtasks)} subtasks"
                )

                # Store decomposed request for later plan generation
                self._decomposed_requests[request_id] = decomposed

                # Check for ambiguities/out-of-scope
                if decomposed.ambiguities or decomposed.out_of_scope:
                    return {
                        "request_id": request_id,
                        "status": "requires_clarification",
                        "ambiguities": decomposed.ambiguities,
                        "out_of_scope": decomposed.out_of_scope,
                    }

                return {
                    "request_id": request_id,
                    "status": "parsing_complete",
                    "decomposed_request": decomposed.model_dump(),
                }

            except Exception as decomp_err:
                self.logger.error(f"Decomposition failed: {decomp_err}")
                return {
                    "request_id": request_id,
                    "status": "parsing_failed",
                    "error": str(decomp_err),
                }

        except ValueError as e:
            self.logger.error(f"Invalid request: {e}")
            raise

    async def generate_plan(self, request_id: str) -> dict:
        """Generate an execution plan from a submitted request.

        Args:
            request_id: ID of a previously submitted request

        Returns:
            dict with plan_id, tasks, summary, status

        Raises:
            ValueError: If request not found or plan generation fails
        """
        try:
            self.logger.info(f"Generating plan for request {request_id}")

            if not self.planner:
                raise ValueError("WorkPlanner not initialized")

            # Retrieve decomposed request from in-memory store
            decomposed_request = self._decomposed_requests.get(request_id)
            if not decomposed_request:
                raise ValueError(f"Decomposed request not found for request_id={request_id}")

            # Get available resources (simplified - would query agent pool)
            available_resources = {"gpu_vram_mb": 8192, "cpu_cores": 16}

            # Generate plan by calling WorkPlanner
            try:
                # Call WorkPlanner.generate_plan() with decomposed request
                plan = await self.planner.generate_plan(decomposed_request, available_resources)

                # Ensure plan has a proper plan_id and request_id
                if not plan.plan_id:
                    plan.plan_id = str(uuid4())
                plan.request_id = request_id

                self.logger.info(
                    f"Generated plan {plan.plan_id} with {len(plan.tasks)} tasks, "
                    f"complexity={plan.complexity_level}"
                )

                # Store plan mapping
                self._request_plans[request_id] = plan

                # Check fallback decision
                if self.fallback:
                    try:
                        fallback_decision, use_claude = await self.fallback.should_use_external_ai(plan)
                        plan.will_use_external_ai = use_claude
                        self.logger.info(f"Fallback decision: {fallback_decision.decision}")
                    except Exception as fallback_err:
                        self.logger.warning(f"Fallback check failed: {fallback_err}")

                return {
                    "plan_id": plan.plan_id,
                    "request_id": request_id,
                    "tasks": [t.model_dump() for t in plan.tasks],
                    "human_readable_summary": plan.human_readable_summary,
                    "complexity_level": plan.complexity_level,
                    "will_use_external_ai": plan.will_use_external_ai,
                    "status": "pending_approval",
                }

            except Exception as plan_err:
                self.logger.error(f"Plan generation failed: {plan_err}")
                return {"status": "planning_failed", "error": str(plan_err)}

        except ValueError as e:
            self.logger.error(f"Invalid request: {e}")
            raise

    async def approve_plan(self, plan_id: str, approved: bool = True) -> dict:
        """Approve or reject a generated plan.

        Args:
            plan_id: ID of plan to approve
            approved: True to approve, False to reject

        Returns:
            dict with plan_id, status, and dispatch_started if approved

        Raises:
            ValueError: If plan not found
        """
        try:
            self.logger.info(f"Approving plan {plan_id}: approved={approved}")

            # Find plan in mapping
            plan = None
            for request_id, p in self._request_plans.items():
                if p.plan_id == plan_id:
                    plan = p
                    break

            if not plan:
                raise ValueError(f"Plan not found: {plan_id}")

            if approved:
                plan.status = "approved"
                plan.approved_at = datetime.utcnow()
                self.logger.info(f"Plan {plan_id} approved at {plan.approved_at}")

                # Begin dispatch
                dispatch_result = await self.dispatch_plan(plan_id)
                return {
                    "plan_id": plan_id,
                    "status": "approved",
                    "dispatch_started": True,
                    "dispatch_result": dispatch_result,
                }
            else:
                plan.status = "rejected"
                self.logger.info(f"Plan {plan_id} rejected")
                return {"plan_id": plan_id, "status": "rejected"}

        except ValueError as e:
            self.logger.error(f"Invalid plan: {e}")
            raise

    async def dispatch_plan(self, plan_id: str) -> dict:
        """Dispatch an approved plan to agents via routing.

        Routes each task to the best available agent using AgentRouter.
        Publishes tasks to RabbitMQ for execution.

        Args:
            plan_id: ID of plan to dispatch

        Returns:
            dict with plan_id, status, dispatched_tasks

        Raises:
            ValueError: If plan not found
        """
        try:
            self.logger.info(f"Dispatching plan {plan_id}")

            if not self.router:
                raise ValueError("AgentRouter not initialized")

            # Find plan
            plan = None
            for request_id, p in self._request_plans.items():
                if p.plan_id == plan_id:
                    plan = p
                    break

            if not plan:
                raise ValueError(f"Plan not found: {plan_id}")

            dispatched_tasks = []

            # Dispatch each task via AgentRouter
            for task in plan.tasks:
                try:
                    # Route task to best agent using AgentRouter
                    agent_selection = await self.router.route_task(task)

                    # Generate unique task ID and dispatch
                    task_id = uuid4()
                    dispatch_result = await self.dispatch_work(
                        task_id=task_id,
                        work_type=task.work_type,
                        parameters=task.parameters,
                        priority=3,
                    )

                    # Record routing decision (AgentRouter already does this)
                    dispatched_tasks.append({
                        **dispatch_result,
                        "agent_id": str(agent_selection.agent_id),
                        "agent_type": agent_selection.agent_type,
                        "routing_score": agent_selection.score,
                        "selection_reason": agent_selection.selected_reason,
                    })

                    self.logger.info(
                        f"Dispatched task {task.name} (task_id={task_id}) "
                        f"to agent {agent_selection.agent_id} (score={agent_selection.score})"
                    )
                except Exception as task_err:
                    self.logger.error(f"Failed to dispatch task {task.name}: {task_err}")
                    dispatched_tasks.append({
                        "name": task.name,
                        "work_type": task.work_type,
                        "error": str(task_err),
                    })

            plan.status = "executing"
            self.logger.info(
                f"Plan {plan_id} now executing ({len(dispatched_tasks)} tasks dispatched)"
            )

            return {
                "plan_id": plan_id,
                "status": "executing",
                "dispatched_tasks": dispatched_tasks,
            }

        except ValueError as e:
            self.logger.error(f"Invalid plan: {e}")
            raise

    async def get_plan_status(self, plan_id: str) -> dict:
        """Get execution status of a dispatched plan.

        Args:
            plan_id: ID of plan to query

        Returns:
            dict with plan status and task summaries

        Raises:
            ValueError: If plan not found
        """
        try:
            # Find plan
            plan = None
            for request_id, p in self._request_plans.items():
                if p.plan_id == plan_id:
                    plan = p
                    break

            if not plan:
                raise ValueError(f"Plan not found: {plan_id}")

            # Summarize execution progress
            return {
                "plan_id": plan_id,
                "request_id": plan.request_id,
                "status": plan.status,
                "tasks": [{"order": t.order, "name": t.name, "work_type": t.work_type} for t in plan.tasks],
                "complexity_level": plan.complexity_level,
                "will_use_external_ai": plan.will_use_external_ai,
                "created_at": plan.created_at.isoformat() if plan.created_at else None,
                "approved_at": plan.approved_at.isoformat() if plan.approved_at else None,
            }

        except ValueError as e:
            self.logger.error(f"Invalid plan: {e}")
            raise

    def initialize_components(
        self,
        decomposer: Optional[RequestDecomposer] = None,
        planner: Optional[WorkPlanner] = None,
        router: Optional[AgentRouter] = None,
        fallback: Optional[ExternalAIFallback] = None,
    ) -> None:
        """Initialize orchestration components.

        Called during service setup to inject dependencies.

        Args:
            decomposer: RequestDecomposer instance
            planner: WorkPlanner instance
            router: AgentRouter instance
            fallback: ExternalAIFallback instance
        """
        self.decomposer = decomposer
        self.planner = planner
        self.router = router
        self.fallback = fallback
        self.logger.info("Orchestration components initialized")

    # ==================== Phase 4: Agent Capacity Queries ====================

    async def get_agent_capacity(self, agent_id: UUID, db: Session) -> dict:
        """Get single agent's current capacity.

        Args:
            agent_id: UUID of agent to query
            db: Database session

        Returns:
            Dict with:
            {
                "agent_id": str(UUID),
                "status": "online" | "offline" | "busy",
                "cpu_cores_available": int,
                "cpu_cores_physical": int,
                "cpu_load_1min": float,
                "cpu_load_5min": float,
                "memory_available_gb": float,
                "gpu_vram_available_gb": float,
                "gpu_vram_total_gb": float,
                "gpu_type": str,
                "timestamp": ISO 8601
            }

        Raises:
            ValueError: If agent not found
        """
        try:
            # Query agent by ID
            agent = db.query(AgentRegistry).filter(AgentRegistry.agent_id == agent_id).first()
            if not agent:
                self.logger.warning(f"Agent not found: {agent_id}")
                raise ValueError(f"Agent not found: {agent_id}")

            # Extract resource metrics
            metrics = agent.resource_metrics or {}

            # Build capacity response
            capacity = {
                "agent_id": str(agent.agent_id),
                "status": agent.status,
                "cpu_cores_available": metrics.get("cpu_cores_available", 0),
                "cpu_cores_physical": metrics.get("cpu_cores_physical", 0),
                "cpu_load_1min": metrics.get("cpu_load_1min", 0.0),
                "cpu_load_5min": metrics.get("cpu_load_5min", 0.0),
                "memory_available_gb": metrics.get("memory_available_gb", 0.0),
                "gpu_vram_available_gb": metrics.get("gpu_vram_available_gb", 0.0),
                "gpu_vram_total_gb": metrics.get("gpu_vram_total_gb", 0.0),
                "gpu_type": metrics.get("gpu_type", "none"),
                "timestamp": agent.last_heartbeat_at.isoformat() if agent.last_heartbeat_at else None,
            }

            self.logger.debug(f"Agent capacity: {agent_id} -> {capacity}")
            return capacity

        except ValueError:
            raise
        except Exception as e:
            self.logger.error(f"Error fetching agent capacity: {e}", exc_info=True)
            raise

    async def get_available_capacity(
        self,
        min_gpu_vram_gb: float = 0.0,
        min_cpu_cores: int = 1,
        db: Session = None,
    ) -> list[dict]:
        """Find agents with available capacity.

        Args:
            min_gpu_vram_gb: Minimum GPU VRAM required in GB (default 0, any GPU OK)
            min_cpu_cores: Minimum available CPU cores (default 1)
            db: Database session

        Returns:
            List of dicts, each with:
            {
                "agent_id": str(UUID),
                "agent_type": str,
                "pool_name": str,
                "status": "online",
                "gpu_vram_available_gb": float,
                "cpu_cores_available": int,
                "cpu_load_1min": float,
                "last_heartbeat_at": ISO 8601
            }
        """
        try:
            # Query online desktop agents
            agents = db.query(AgentRegistry).filter(
                AgentRegistry.agent_type == "desktop",
                AgentRegistry.status == "online"
            ).all()

            result = []

            # Filter agents by resource requirements
            for agent in agents:
                try:
                    metrics = agent.resource_metrics or {}
                    gpu_vram = metrics.get("gpu_vram_available_gb", 0.0)
                    cpu_cores = metrics.get("cpu_cores_available", 0)

                    # Check if agent meets requirements
                    if gpu_vram >= min_gpu_vram_gb and cpu_cores >= min_cpu_cores:
                        result.append({
                            "agent_id": str(agent.agent_id),
                            "agent_type": agent.agent_type,
                            "pool_name": agent.pool_name,
                            "status": agent.status,
                            "gpu_vram_available_gb": gpu_vram,
                            "cpu_cores_available": cpu_cores,
                            "cpu_load_1min": metrics.get("cpu_load_1min", 0.0),
                            "last_heartbeat_at": agent.last_heartbeat_at.isoformat() if agent.last_heartbeat_at else None,
                        })
                except Exception as agent_err:
                    self.logger.warning(f"Error processing agent {agent.agent_id}: {agent_err}")
                    # Skip this agent and continue

            self.logger.info(
                f"Found {len(result)} agents with capacity "
                f"(min_gpu={min_gpu_vram_gb}GB, min_cpu={min_cpu_cores})"
            )
            return result

        except Exception as e:
            self.logger.error(f"Error fetching available capacity: {e}", exc_info=True)
            raise
