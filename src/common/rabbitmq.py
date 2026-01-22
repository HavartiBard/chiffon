"""RabbitMQ queue topology and connection management.

This module provides:
- Queue and exchange declarations for the Chiffon message bus
- Connection string management
- Durable queue topology with priority and dead-letter support

Queue Architecture:
- work_queue: Durable queue for work dispatch from orchestrator to agents (priority-enabled)
- reply_queue: Durable queue for agent status updates and results back to orchestrator
- broadcast_exchange: Fanout exchange for system-wide announcements (pause/resume, maintenance)
- dlx_exchange: Dead-letter exchange for unrecoverable messages
- dlx_queue: Queue for messages that failed after retries

All queues except broadcast are durable (metadata persisted to disk).
Priority levels: 1-5 (5=critical/highest, 1=background/lowest).
Dead-letter routing prevents infinite retry loops.
"""

import logging
from typing import Dict

import aio_pika
from aio_pika import ExchangeType

from src.common.config import Config

logger = logging.getLogger(__name__)


async def declare_queues(
    channel: aio_pika.Channel,
) -> Dict[str, aio_pika.Queue | aio_pika.Exchange]:
    """Declare all required queues and exchanges for the Chiffon message bus.

    This function declares the complete queue topology that agents use for communication.
    All declarations are idempotent - calling this function multiple times is safe.

    Args:
        channel: An aio_pika.Channel object with an established AMQP connection.

    Returns:
        Dictionary with keys:
        - 'work_queue': aio_pika.Queue - receives work requests from orchestrator
        - 'reply_queue': aio_pika.Queue - receives status updates and results from agents
        - 'broadcast_exchange': aio_pika.Exchange - fanout for system announcements
        - 'dlx_queue': aio_pika.Queue - receives failed messages after retries

    Raises:
        aio_pika.AMQPException: If queue/exchange declaration fails on broker.
        aio_pika.AMQPConnectionError: If connection to RabbitMQ is lost.

    Example:
        >>> import aio_pika
        >>> connection = await aio_pika.connect_robust("amqp://guest:guest@localhost/")
        >>> channel = await connection.channel()
        >>> topology = await declare_queues(channel)
        >>> print(f"Work queue ready: {topology['work_queue']}")
    """

    try:
        # Work queue: durable, priority-enabled, dead-letter routing
        # Used for work dispatch from orchestrator to any agent type.
        # Agents filter by type header locally.
        logger.info("Declaring work_queue")
        work_queue = await channel.declare_queue(
            "work_queue",
            durable=True,
            arguments={
                "x-max-priority": 5,  # Priority levels 1-5 (5=highest)
                "x-dead-letter-exchange": "dlx_exchange",  # Route failed messages to DLX
            },
        )
        logger.info("work_queue declared successfully")

        # Reply queue: durable, receives status updates and work results
        # Single consumer (orchestrator) listens, correlates via request_id + trace_id.
        logger.info("Declaring reply_queue")
        reply_queue = await channel.declare_queue(
            "reply_queue",
            durable=True,
            arguments={"x-dead-letter-exchange": "dlx_exchange"},
        )
        logger.info("reply_queue declared successfully")

        # Broadcast exchange: fanout, transient (no persistence)
        # Used for system announcements: pause/resume, maintenance alerts, quota warnings.
        # Each agent binds its own queue to this exchange.
        logger.info("Declaring broadcast_exchange")
        broadcast_exchange = await channel.declare_exchange(
            "broadcast_exchange",
            ExchangeType.FANOUT,
            durable=False,
        )
        logger.info("broadcast_exchange declared successfully")

        # Dead-letter exchange: direct, durable
        # Routes unrecoverable messages (after N retries) for inspection.
        # Prevents infinite retry loops; manual inspection required.
        logger.info("Declaring dlx_exchange (dead-letter)")
        dlx_exchange = await channel.declare_exchange(
            "dlx_exchange",
            ExchangeType.DIRECT,
            durable=True,
        )
        logger.info("dlx_exchange declared successfully")

        # Dead-letter queue: durable, max-length=10000
        # Holds failed messages for post-mortem debugging.
        # If DLX queue reaches max-length, oldest messages are discarded.
        logger.info("Declaring dlx_queue")
        dlx_queue = await channel.declare_queue(
            "dlx_queue",
            durable=True,
            arguments={"x-max-length": 10000},
        )
        logger.info("dlx_queue declared successfully")

        # Bind dlx_queue to dlx_exchange with empty routing key (catch-all)
        logger.info("Binding dlx_queue to dlx_exchange")
        await dlx_queue.bind(dlx_exchange, routing_key="")
        logger.info("dlx_queue binding established")

        logger.info("All queues and exchanges declared successfully")
        return {
            "work_queue": work_queue,
            "reply_queue": reply_queue,
            "broadcast_exchange": broadcast_exchange,
            "dlx_queue": dlx_queue,
        }

    except aio_pika.AMQPException as e:
        logger.error(f"Failed to declare queues/exchanges: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Unexpected error declaring queues: {e}", exc_info=True)
        raise


def get_connection_string() -> str:
    """Get the RabbitMQ connection string from configuration.

    Reads RABBITMQ_URL from the Config class, which loads from environment variables
    or .env file. Falls back to a safe localhost default.

    Returns:
        AMQP connection string suitable for aio_pika.connect_robust()

    Example:
        >>> url = get_connection_string()
        >>> print(url)
        amqp://guest:guest@rabbitmq:5672/

        >>> import aio_pika
        >>> connection = await aio_pika.connect_robust(url)
    """
    config = Config()
    return config.RABBITMQ_URL
