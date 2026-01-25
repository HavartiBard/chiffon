"""FastAPI orchestrator application.

Entry point for the Chiffon agent orchestration system.
Provides REST API endpoints, background tasks, and dependency injection.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

import aio_pika
from fastapi import FastAPI

from src.common.config import Config
from src.common.database import SessionLocal
from src.common.protocol import MessageEnvelope, StatusUpdate, WorkResult
from src.orchestrator.api import router
from src.orchestrator.service import OrchestratorService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Load configuration
config = Config()


class WebSocketManager:
    """Manages WebSocket subscriptions for real-time task updates."""

    def __init__(self):
        """Initialize empty subscription map."""
        self.subscriptions: dict[str, list] = {}

    def subscribe(self, trace_id: str, websocket) -> None:
        """Subscribe a WebSocket to updates for a trace_id.

        Args:
            trace_id: Trace ID to subscribe to
            websocket: WebSocket connection object
        """
        if trace_id not in self.subscriptions:
            self.subscriptions[trace_id] = []
        self.subscriptions[trace_id].append(websocket)

    def unsubscribe(self, trace_id: str, websocket) -> None:
        """Unsubscribe a WebSocket.

        Args:
            trace_id: Trace ID to unsubscribe from
            websocket: WebSocket connection object
        """
        if trace_id in self.subscriptions and websocket in self.subscriptions[trace_id]:
            self.subscriptions[trace_id].remove(websocket)

    async def broadcast(self, trace_id: str, message: dict) -> None:
        """Broadcast message to all subscribers for a trace_id.

        Args:
            trace_id: Trace ID to broadcast to
            message: Message dict to send
        """
        if trace_id in self.subscriptions:
            disconnected = []
            for ws in self.subscriptions[trace_id]:
                try:
                    await ws.send_json(message)
                except Exception as e:
                    logger.warning(f"WebSocket send failed: {e}")
                    disconnected.append(ws)

            # Clean up disconnected websockets
            for ws in disconnected:
                self.subscriptions[trace_id].remove(ws)


async def consume_heartbeats(orchestrator_service: OrchestratorService) -> None:
    """Background task: Listen for agent heartbeat updates.

    Consumes StatusUpdate messages from reply_queue and registers agents.
    Runs continuously; reconnects on failure.

    Args:
        orchestrator_service: Orchestrator service to update agent registry
    """
    try:
        logger.info("Starting heartbeat listener")
        connection = await aio_pika.connect_robust(config.RABBITMQ_URL)

        async with connection:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=1)

            queue = await channel.get_queue("reply_queue")

            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    async with message.process():
                        try:
                            # Deserialize message
                            envelope_data = json.loads(message.body.decode())
                            envelope = MessageEnvelope(**envelope_data)

                            # Only process status updates
                            if envelope.type != "work_status":
                                continue

                            # Deserialize payload
                            status_update = StatusUpdate(**envelope.payload)

                            # Register agent
                            await orchestrator_service.register_agent(
                                agent_id=status_update.agent_id,
                                agent_type=status_update.agent_type,
                                status=status_update.status,
                                resources=status_update.resources,
                            )

                            logger.debug(
                                "Agent registered",
                                extra={
                                    "agent_id": str(status_update.agent_id),
                                    "agent_type": status_update.agent_type,
                                    "status": status_update.status,
                                },
                            )

                        except Exception as e:
                            logger.error(f"Error processing heartbeat: {e}", exc_info=True)

    except asyncio.CancelledError:
        logger.info("Heartbeat listener cancelled")
    except Exception as e:  # Catches AMQPConnectionError and others
        logger.error(f"Heartbeat listener error: {e}", exc_info=True)


async def consume_work_results(orchestrator_service: OrchestratorService) -> None:
    """Background task: Listen for work results from agents.

    Consumes WorkResult messages from reply_queue and updates task state.
    Broadcasts to WebSocket subscribers via trace_id.
    Runs continuously; reconnects on failure.

    Args:
        orchestrator_service: Orchestrator service to update task state
    """
    try:
        logger.info("Starting result listener")
        connection = await aio_pika.connect_robust(config.RABBITMQ_URL)

        async with connection:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=1)

            queue = await channel.get_queue("reply_queue")

            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    async with message.process():
                        try:
                            # Deserialize message
                            envelope_data = json.loads(message.body.decode())
                            envelope = MessageEnvelope(**envelope_data)

                            # Only process work results
                            if envelope.type != "work_result":
                                continue

                            # Deserialize payload
                            work_result = WorkResult(**envelope.payload)

                            # Handle result (update DB, broadcast)
                            await orchestrator_service.handle_work_result(
                                work_result=work_result,
                                trace_id=envelope.trace_id,
                            )

                            logger.debug(
                                "Work result processed",
                                extra={
                                    "trace_id": str(envelope.trace_id),
                                    "task_id": str(work_result.task_id),
                                    "status": work_result.status,
                                },
                            )

                        except Exception as e:
                            logger.error(f"Error processing work result: {e}", exc_info=True)

    except asyncio.CancelledError:
        logger.info("Result listener cancelled")
    except Exception as e:  # Catches AMQPConnectionError and others
        logger.error(f"Result listener error: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for application startup and shutdown.

    Startup: Initialize database, RabbitMQ, background tasks, and routers.
    Shutdown: Cleanup background tasks and connections.
    """
    # Startup
    logger.info(f"Starting {config.APP_NAME}")
    logger.info(f"Database: {config.DATABASE_URL}")
    logger.info(f"RabbitMQ: {config.RABBITMQ_URL}")

    # Initialize database session
    db_session = SessionLocal()

    # Create orchestrator service
    orchestrator_service = OrchestratorService(config=config, db_session=db_session)

    # Connect to RabbitMQ
    try:
        await orchestrator_service.connect()
        logger.info("RabbitMQ connection established")
    except Exception as e:
        logger.error(f"Failed to connect to RabbitMQ: {e}")
        db_session.close()
        raise

    # Store in app state
    app.state.orchestrator_service = orchestrator_service
    app.state.ws_manager = WebSocketManager()

    # Set up dependency injection
    async def get_service():
        return orchestrator_service

    api_module = __import__("src.orchestrator.api", fromlist=["get_orchestrator_service"])
    app.dependency_overrides[api_module.get_orchestrator_service] = get_service

    # Start background tasks
    heartbeat_task = asyncio.create_task(consume_heartbeats(orchestrator_service))
    result_task = asyncio.create_task(consume_work_results(orchestrator_service))

    logger.info("Background tasks started")

    yield

    # Shutdown
    logger.info(f"Shutting down {config.APP_NAME}")

    # Cancel background tasks
    heartbeat_task.cancel()
    result_task.cancel()

    try:
        await asyncio.gather(heartbeat_task, result_task)
    except asyncio.CancelledError:
        pass

    # Disconnect from RabbitMQ
    await orchestrator_service.disconnect()

    # Close database session
    db_session.close()

    logger.info("Cleanup complete")


# Create FastAPI app
app = FastAPI(
    title=config.APP_NAME,
    description="Orchestrated AI agents for infrastructure automation",
    version="0.1.0",
    lifespan=lifespan,
)

# Include orchestrator API router
app.include_router(router)


@app.get("/health")
async def health():
    """Health check endpoint.

    Returns:
        dict: Status of the application and its dependencies.
    """
    return {
        "status": "healthy",
        "service": config.APP_NAME,
        "version": "0.1.0",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
