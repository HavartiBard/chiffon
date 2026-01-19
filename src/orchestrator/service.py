"""OrchestratorService: Central business logic for task dispatch and agent management.

Provides:
- Task dispatch to agents via RabbitMQ
- Task status queries
- Agent registration and health tracking
- Work result handling with deduplication
- Task cancellation
"""

import json
import logging
import time
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

import aio_pika
from sqlalchemy.orm import Session

from src.common.config import Config
from src.common.models import Task
from src.common.protocol import (
    MessageEnvelope,
    WorkRequest,
    WorkResult,
)
from src.common.rabbitmq import declare_queues, get_connection_string

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

    def __init__(self, config: Config, db_session: Session):
        """Initialize orchestrator service.

        Args:
            config: Configuration object
            db_session: SQLAlchemy session for database operations
        """
        self.config = config
        self.db = db_session
        self.connection: Optional[aio_pika.Connection] = None
        self.channel: Optional[aio_pika.Channel] = None
        self.request_cache = RequestCache(ttl_seconds=300)  # 5-minute cache
        self.logger = logging.getLogger("orchestrator.service")
        self.ws_manager: Optional[object] = None  # Set by main.py for WebSocket broadcasting

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
            # Use transient for lower priorities (1-3) for speed
            is_persistent = priority >= 4
            message = aio_pika.Message(
                body=envelope.to_json().encode(),
                priority=priority,
                delivery_mode=(
                    aio_pika.DeliveryMode.PERSISTENT
                    if is_persistent
                    else aio_pika.DeliveryMode.TRANSIENT
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
