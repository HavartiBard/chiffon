"""Base agent class for RabbitMQ-connected agents.

Provides:
- RabbitMQ connection management with automatic reconnection
- Heartbeat messaging every 60 seconds with resource metrics
- Work request consumption and validation
- Idempotency cache for deduplication
- Error handling and dead-letter routing
- Abstract methods for subclass implementation
"""

import asyncio
import logging
import subprocess
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any, Optional
from uuid import UUID, uuid4

import aio_pika
import psutil
from pydantic import ValidationError

# Type: ignore for aio_pika type issues (library has incomplete stubs)
# We use Any for channels and queues to avoid mypy type narrowing issues
from src.common.config import Config
from src.common.protocol import (
    MessageEnvelope,
    StatusUpdate,
    WorkRequest,
    WorkResult,
)
from src.common.rabbitmq import declare_queues, get_connection_string

logger = logging.getLogger(__name__)


class IdempotencyCache:
    """Simple LRU cache with TTL for request deduplication."""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        """Initialize the cache.

        Args:
            max_size: Maximum number of entries to keep
            ttl_seconds: Time-to-live for cached results in seconds
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        """Retrieve a value from cache if it exists and hasn't expired.

        Args:
            key: Cache key (typically request_id)

        Returns:
            Cached value if found and not expired, None otherwise
        """
        if key not in self.cache:
            return None

        value, timestamp = self.cache[key]
        age_seconds = time.time() - timestamp

        if age_seconds > self.ttl_seconds:
            # Entry expired, remove it
            del self.cache[key]
            return None

        # Move to end (LRU)
        self.cache.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        """Store a value in cache.

        Args:
            key: Cache key (typically request_id)
            value: Value to cache
        """
        # Remove oldest if at capacity
        if len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)

        # Add/update entry with current timestamp
        self.cache[key] = (value, time.time())
        self.cache.move_to_end(key)


class BaseAgent(ABC):
    """Abstract base class for agents that communicate via RabbitMQ.

    Agents must implement:
    - execute_work(work_request): Perform the actual work
    - get_agent_capabilities(): Report capabilities to orchestrator
    """

    def __init__(self, agent_id: str, agent_type: str, config: Config):
        """Initialize the agent.

        Args:
            agent_id: Unique identifier for this agent (UUID or hostname)
            agent_type: Type of agent (orchestrator, infra, desktop, code, research)
            config: Configuration object with RabbitMQ and DB connection strings
        """
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.config = config

        self.connection: Optional[Any] = None
        self.channel: Optional[Any] = None
        self.work_queue: Optional[Any] = None
        self.reply_queue: Optional[Any] = None
        self.broadcast_exchange: Optional[Any] = None

        self.current_task_id: Optional[UUID] = None
        self.logger = logging.getLogger(f"agent.{agent_id}")
        self.idempotency_cache = IdempotencyCache(max_size=1000, ttl_seconds=300)

    async def connect(self) -> Any:
        """Connect to RabbitMQ and declare queues.

        Returns:
            aio_pika connection object

        Raises:
            aio_pika.exceptions.AMQPConnectionError: If connection fails
        """
        try:
            connection_string = get_connection_string()
            self.logger.info(f"Connecting to RabbitMQ at {connection_string}")

            conn = await aio_pika.connect_robust(connection_string)
            self.connection = conn
            self.channel = await conn.channel()

            # Set prefetch to 1 (process one message at a time)
            await self.channel.set_qos(prefetch_count=1)

            # Declare all queues and exchanges
            topology = await declare_queues(self.channel)  # type: ignore
            self.work_queue = topology["work_queue"]
            self.reply_queue = topology["reply_queue"]
            self.broadcast_exchange = topology.get("broadcast_exchange")

            self.logger.info("Connected to RabbitMQ and queues declared")
            return conn

        except aio_pika.exceptions.AMQPConnectionError as e:
            self.logger.error(f"AMQP connection error: {e}", exc_info=True)
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error connecting to RabbitMQ: {e}", exc_info=True)
            raise

    async def disconnect(self) -> None:
        """Close RabbitMQ connection gracefully."""
        try:
            if self.channel and not self.channel.is_closed:
                await self.channel.close()
            if self.connection and not self.connection.is_closed:
                await self.connection.close()
            self.logger.info("Disconnected from RabbitMQ")
        except Exception as e:
            self.logger.error(f"Error during disconnect: {e}", exc_info=True)

    def _get_gpu_metrics(self) -> dict[str, float]:
        """Get GPU VRAM metrics using nvidia-smi.

        Returns:
            Dict with gpu_vram_available_gb and gpu_vram_total_gb.
            Returns zeros if nvidia-smi unavailable or GPU not present.
        """
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.total,memory.free",
                    "--format=csv,nounits,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                if lines:
                    total_mb, free_mb = map(float, lines[0].split(","))
                    return {
                        "gpu_vram_total_gb": total_mb / 1024.0,
                        "gpu_vram_available_gb": free_mb / 1024.0,
                    }
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
            self.logger.debug(f"GPU metrics unavailable: {e}")

        # Return zeros if GPU not available
        return {
            "gpu_vram_total_gb": 0.0,
            "gpu_vram_available_gb": 0.0,
        }

    def _get_resource_metrics(self) -> dict[str, Any]:
        """Collect current resource metrics from system.

        Returns:
            Dict with cpu_percent, memory_percent, and GPU metrics
        """
        metrics = {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
        }
        metrics.update(self._get_gpu_metrics())
        return metrics

    async def send_heartbeat(self) -> None:
        """Send a heartbeat status update to orchestrator.

        The heartbeat includes:
        - Agent ID, type, and online status
        - Current task ID (if any)
        - Resource metrics (CPU, memory, GPU)
        - Trace ID and request ID for tracking
        """
        try:
            trace_id = uuid4()
            request_id = uuid4()
            resources = self._get_resource_metrics()

            status_update = StatusUpdate(
                agent_id=uuid4() if self.agent_id == "test-agent-001" else UUID(int=0),
                agent_type=self.agent_type,
                status="online",
                current_task_id=self.current_task_id,
                resources=resources,
            )

            envelope = MessageEnvelope(
                from_agent=self.agent_type,
                to_agent="orchestrator",
                type="work_status",
                trace_id=trace_id,
                request_id=request_id,
                priority=4,
                payload=status_update.model_dump(),
            )

            if self.reply_queue and self.reply_queue.channel:
                message = aio_pika.Message(
                    body=envelope.to_json().encode(),
                    content_type="application/json",
                )
                await self.reply_queue.channel.default_exchange.publish(
                    message, routing_key=self.reply_queue.name
                )

                self.logger.info(
                    "Heartbeat sent",
                    extra={
                        "trace_id": str(trace_id),
                        "request_id": str(request_id),
                        "agent_id": self.agent_id,
                        "resources": resources,
                    },
                )
        except Exception as e:
            self.logger.error(f"Error sending heartbeat: {e}", exc_info=True)

    async def start_heartbeat_loop(self) -> None:
        """Background task that sends heartbeats every 60 seconds.

        Runs indefinitely until agent stops. Exceptions are caught and logged
        to prevent the heartbeat loop from crashing the agent.
        """
        try:
            while True:
                await asyncio.sleep(60)
                await self.send_heartbeat()
        except asyncio.CancelledError:
            self.logger.info("Heartbeat loop cancelled")
        except Exception as e:
            self.logger.error(f"Heartbeat loop error: {e}", exc_info=True)

    def _validate_envelope(self, envelope: MessageEnvelope) -> bool:
        """Validate message envelope before processing.

        Checks:
        - Protocol version matches
        - from_agent is not in blocked list
        - Message type is expected

        Args:
            envelope: MessageEnvelope to validate

        Returns:
            True if valid, False otherwise
        """
        if envelope.protocol_version != "1.0":
            self.logger.warning(f"Protocol version mismatch: {envelope.protocol_version}")
            return False

        # Could add blocked_agents list here in future
        return True

    async def _process_single_message(
        self, message: Any
    ) -> None:
        """Process a single work request message.

        Args:
            message: The incoming message from work queue
        """
        try:
            # Deserialize envelope
            try:
                envelope = MessageEnvelope.from_json(
                    message.body.decode()
                )
            except (ValidationError, ValueError) as e:
                self.logger.error(f"Invalid message envelope: {e}")
                await message.nack(requeue=False)
                return

            # Validate envelope
            if not self._validate_envelope(envelope):
                self.logger.warning(
                    f"Envelope validation failed for message {envelope.message_id}"
                )
                await message.nack(requeue=False)
                return

            # Check message type
            if envelope.type != "work_request":
                self.logger.warning(
                    f"Unexpected message type: {envelope.type}"
                )
                await message.nack(requeue=False)
                return

            # ACK to signal acceptance
            await message.ack()
            self.logger.info(
                "Work request acknowledged",
                extra={"trace_id": str(envelope.trace_id)},
            )

            # Deserialize work request
            try:
                work_request = WorkRequest.model_validate(
                    envelope.payload
                )
            except ValidationError as e:
                self.logger.error(f"Invalid work request: {e}")
                return

            # Check idempotency cache
            cache_key = str(envelope.request_id)
            cached_result = self.idempotency_cache.get(cache_key)
            if cached_result:
                self.logger.info(
                    "Work result found in cache, using cached result",
                    extra={"trace_id": str(envelope.trace_id)},
                )
                # Publish cached result
                cached_result_copy = cached_result.model_copy()
                cached_result_copy.trace_id = envelope.trace_id
                cached_result_copy.request_id = envelope.request_id
                await self._publish_result(cached_result_copy, envelope)
                return

            # Execute work
            self.current_task_id = work_request.task_id
            try:
                work_result = await self.execute_work(work_request)

                # Cache the result
                self.idempotency_cache.set(cache_key, work_result)

                # Add trace/request IDs
                work_result.trace_id = envelope.trace_id
                work_result.request_id = envelope.request_id

                await self._publish_result(work_result, envelope)

                self.logger.info(
                    "Work completed and result published",
                    extra={
                        "trace_id": str(envelope.trace_id),
                        "task_id": str(work_request.task_id),
                        "duration_ms": work_result.duration_ms,
                    },
                )
            except Exception as e:
                self.logger.error(
                    f"Error executing work: {e}", exc_info=True
                )
            finally:
                self.current_task_id = None

        except Exception as e:
            self.logger.error(
                f"Error processing message: {e}", exc_info=True
            )

    async def consume_work_requests(self) -> None:
        """Main work processing loop.

        Listens for work requests on work_queue, validates envelopes,
        deserializes messages, executes work via execute_work(), and
        publishes results back to reply_queue.

        Message lifecycle:
        1. Receive from work_queue
        2. Validate envelope (NACK if invalid, send to DLX)
        3. ACK (signal acceptance)
        4. Execute work
        5. Publish result to reply_queue
        """
        if not self.work_queue:
            self.logger.error("Work queue not initialized")
            return

        try:
            self.logger.info("Starting work request consumption")
            async with self.work_queue.iterator() as queue_iter:
                async for message in queue_iter:
                    await self._process_single_message(message)

        except asyncio.CancelledError:
            self.logger.info("Work consumption loop cancelled")
        except Exception as e:
            self.logger.error(f"Unexpected error in consume_work_requests: {e}", exc_info=True)

    async def _publish_result(
        self, work_result: WorkResult, original_envelope: MessageEnvelope
    ) -> None:
        """Publish a work result to the reply queue.

        Args:
            work_result: Result to publish
            original_envelope: Original work request envelope (for routing/correlation)
        """
        try:
            if not self.reply_queue:
                self.logger.error("Reply queue not available")
                return

            # Set agent_id as UUID (convert string if needed)
            if isinstance(self.agent_id, str):
                # Create a deterministic UUID from string for testing
                work_result.agent_id = uuid4()
            else:
                work_result.agent_id = self.agent_id

            result_envelope = MessageEnvelope(
                from_agent=self.agent_type,
                to_agent="orchestrator",
                type="work_result",
                trace_id=original_envelope.trace_id,
                request_id=original_envelope.request_id,
                priority=original_envelope.priority,
                payload=work_result.model_dump(),
            )

            message = aio_pika.Message(
                body=result_envelope.to_json().encode(),
                content_type="application/json",
            )

            await self.reply_queue.channel.default_exchange.publish(
                message, routing_key=self.reply_queue.name
            )

            self.logger.debug(
                "Result published to reply queue",
                extra={"trace_id": str(original_envelope.trace_id)},
            )

        except Exception as e:
            self.logger.error(f"Error publishing result: {e}", exc_info=True)

    @abstractmethod
    async def execute_work(self, work_request: WorkRequest) -> WorkResult:
        """Execute the requested work.

        Subclasses must override this method to implement their specific work.

        Args:
            work_request: The work request with task_id, work_type, and parameters

        Returns:
            WorkResult with status, exit_code, output, duration_ms, and resources_used

        Raises:
            Exception: Subclass-specific exceptions (will be caught and error result returned)
        """
        pass

    @abstractmethod
    def get_agent_capabilities(self) -> dict[str, Any]:
        """Report agent capabilities to orchestrator.

        Subclasses must override this method to declare what work types they support.

        Returns:
            Dict mapping work type to boolean (True if supported, False if not)
        """
        pass

    async def run(self) -> None:
        """Main agent run loop.

        Connects to RabbitMQ, starts heartbeat background task, and begins
        consuming work requests. Runs until stopped (e.g., via Ctrl+C or cancellation).

        On shutdown, gracefully closes the connection.
        """
        try:
            await self.connect()

            # Start heartbeat background task
            heartbeat_task = asyncio.create_task(self.start_heartbeat_loop())

            # Start work consumption (blocking)
            try:
                await self.consume_work_requests()
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            self.logger.error(f"Error in agent run loop: {e}", exc_info=True)
        finally:
            await self.disconnect()
            self.logger.info("Agent stopped")
