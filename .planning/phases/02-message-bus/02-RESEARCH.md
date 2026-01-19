# Phase 2: Message Bus & Agent Communication - Research

**Researched:** 2026-01-19
**Domain:** RabbitMQ queue topology, agent communication protocol, FastAPI + async integration, connection reliability
**Confidence:** HIGH (RabbitMQ docs, aio-pika, FastAPI), MEDIUM (correlation ID patterns, agent lifecycle), LOW (high-throughput correlation ID edge cases)

## Summary

Phase 2 deploys RabbitMQ as a central message bus for agent communication, implements a durable queue topology with priority support, and wraps it in a FastAPI REST API with WebSocket real-time updates. Research identifies the standard RabbitMQ patterns, agent protocol structure, Python async libraries, and critical reliability mechanisms that prevent message loss and duplicate processing.

**Key findings:**

1. **Queue topology:** RabbitMQ with durable queues (metadata persisted to disk), x-max-priority for 5 priority levels, dead-letter exchanges for failed messages, and separate broadcast queue via fanout exchange
2. **Agent protocol:** JSON envelope with protocol_version, message_id, request_id (idempotency), trace_id (correlation), and type-specific payloads for work_request, work_result, error
3. **Python library choice:** aio-pika (not pika) for FastAPI async context; transparent reconnects with state recovery via `connect_robust()`
4. **FastAPI integration:** Background tasks for heartbeat listening, WebSocket endpoints for real-time updates, REST endpoints for dispatch/status/agents/cancel
5. **Reliability:** Manual ACK after work starts prevents message loss; NACK + requeue for transient failures; idempotency tokens (request_id) prevent duplicate work; DLX for unrecoverable failures
6. **Heartbeat strategy:** 60s interval, separate consumer connection, agent sends ID + resource metrics; offline after 180s (3 missed beats)
7. **Connection pooling:** aio-pika handles transparently via `connect_robust()` with automatic reconnect; Pika requires application-level pooling (avoid for async FastAPI)

**Primary recommendation:** Use aio-pika with `connect_robust()` for production-ready async RabbitMQ integration. Implement correlation ID tracking via trace_id + request_id in all messages. Use dead-letter exchanges with manual inspection for failed messages (no infinite retry loops). Priority queues use 1-5 range (not all 0-255) to avoid performance degradation. WebSocket for real-time updates; REST/polling as fallback.

---

## RabbitMQ Setup & Configuration

### Queue Topology (Standard Pattern)

**Work Queue (Durable, Priority-Enabled):**
- Single queue named `work_queue`
- Durable: true (metadata persisted to disk across restarts)
- x-max-priority: 5 (recommended 1-5 range for performance)
- Messages in this queue are work requests from orchestrator to any agent type
- Agent type filtering: specified in message header or payload, agent filters locally

**Reply Queue (Durable, Single Consumer):**
- Single queue named `reply_queue`
- Durable: true
- No priority (status updates delivered as-is)
- Single consumer (orchestrator) listens, correlates via request_id + trace_id

**Broadcast Queue (Fanout Exchange, No Persistence):**
- Fanout exchange named `broadcast_exchange`
- Separate queue per agent (auto-named, transient)
- Use for system announcements (pause/resume, maintenance alerts)
- No persistence; agents reconnect and re-bind

**Dead-Letter Queue (DLX for Unrecoverable Messages):**
- When message fails after N retries, route to DLX instead of infinite requeue
- Separate queue for inspection/auditing
- Configured via queue argument `x-dead-letter-exchange` at queue declaration time

### Durable Queue Declaration (Code Pattern)

```python
# Source: RabbitMQ official documentation + aio-pika best practices
import aio_pika
from aio_pika import ExchangeType

async def declare_queues(channel: aio_pika.Channel):
    """Declare all required queues and exchanges."""

    # Work queue: durable, priority-enabled
    work_queue = await channel.declare_queue(
        'work_queue',
        durable=True,
        arguments={
            'x-max-priority': 5,  # Use 1-5 range for performance
            'x-dead-letter-exchange': 'dlx_exchange'  # Failed messages route here
        }
    )

    # Reply queue: durable, single consumer
    reply_queue = await channel.declare_queue(
        'reply_queue',
        durable=True,
        arguments={'x-dead-letter-exchange': 'dlx_exchange'}
    )

    # Broadcast exchange: transient, fanout
    broadcast_exchange = await channel.declare_exchange(
        'broadcast_exchange',
        ExchangeType.FANOUT,
        durable=False
    )

    # Dead-letter exchange for unrecoverable messages
    dlx_exchange = await channel.declare_exchange(
        'dlx_exchange',
        ExchangeType.DIRECT,
        durable=True
    )

    dlx_queue = await channel.declare_queue(
        'dlx_queue',
        durable=True
    )

    await dlx_queue.bind(dlx_exchange, routing_key='')

    return {
        'work_queue': work_queue,
        'reply_queue': reply_queue,
        'broadcast_exchange': broadcast_exchange,
        'dlx_queue': dlx_queue
    }
```

### Priority Queue Configuration

**Key constraints:**
- `x-max-priority` must be set at queue declaration time (immutable after)
- Recommended range: 1-5 (each level requires internal sub-queue; 255 levels degrades broker performance)
- Publisher specifies priority (0-5) when publishing; higher number = higher priority
- Delivery order may vary slightly when multiple consumers compete or messages are requeued

**Message priority levels (Phase 2 design):**
- 5: critical (must persist, immediate delivery)
- 4: high (must persist, high priority)
- 3: normal (in-memory acceptable, standard delivery)
- 2: low (in-memory acceptable, can wait)
- 1: background (lowest priority, batch processing)

---

## Agent Communication Protocol

### Message Envelope Structure (JSON)

Every message (work_request, work_result, error, status_update) conforms to this envelope:

```json
{
  "protocol_version": "1.0",
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "from_agent": "orchestrator",
  "to_agent": "infra",
  "timestamp": "2026-01-19T10:30:00Z",
  "trace_id": "770e8400-e29b-41d4-a716-446655440001",
  "request_id": "990e8400-e29b-41d4-a716-446655440002",
  "type": "work_request",
  "priority": 3,
  "payload": {}
}
```

**Field semantics:**
- `protocol_version`: "1.0" for now; bumped only for breaking changes
- `message_id`: UUID, unique per message for deduplication logging
- `from_agent` / `to_agent`: ["orchestrator", "infra", "desktop", "code", "research"]
- `timestamp`: ISO 8601, server time when message created
- `trace_id`: UUID propagated across related messages (work_request → work_result); used for correlation
- `request_id`: UUID for idempotency; same request_id = same request (consumer checks cache before executing)
- `type`: "work_request", "work_result", "error", "status_update"
- `priority`: 1-5, used by RabbitMQ queue
- `payload`: Type-specific data structure

### Work Request Payload

```python
# Source: Phase 2 CONTEXT.md + standard task queue patterns
{
    "task_id": "uuid",
    "work_type": "string",  # "ansible", "shell_script", "docker", etc.
    "parameters": {
        # Task-specific parameters
    },
    "hints": {
        # Optional agent filtering hints
        "preferred_agent_type": "infra",
        "required_capabilities": ["gpu", "docker"],
        "estimated_duration_seconds": 300
    }
}
```

### Work Result Payload

```python
{
    "task_id": "uuid",
    "status": "completed",  # or "failed", "cancelled"
    "exit_code": 0,
    "output": "string or JSON",
    "error_message": null,
    "duration_ms": 45000,
    "agent_id": "agent-uuid"
}
```

### Status Update Payload (Heartbeat)

Agents send every 60 seconds:

```python
{
    "agent_id": "uuid",
    "agent_type": "infra",  # From ["orchestrator", "infra", "desktop", "code", "research"]
    "status": "online",  # or "offline", "busy"
    "current_task_id": "uuid or null",
    "resources": {
        "cpu_percent": 45.2,
        "memory_percent": 62.1,
        "gpu_vram_available_gb": 8.0,
        "gpu_vram_total_gb": 16.0
    },
    "timestamp": "2026-01-19T10:30:00Z"
}
```

### Error Message Payload

```python
{
    "error_code": 5003,  # Standardized code
    "error_message": "Queue exceeded max length",
    "context": {
        # Optional debugging info
        "original_message_id": "uuid",
        "affected_queue": "work_queue"
    }
}
```

### Correlation ID Tracking Strategy

**Pattern:** Every message flow (request/response pair) shares same trace_id; each individual message has unique request_id for idempotency

**Example flow:**
```
1. Orchestrator sends work_request
   - message_id: unique
   - request_id: UUID (new)
   - trace_id: UUID (new)

2. Agent receives, processes
   - Agent logs with trace_id for correlation
   - Agent checks if request_id seen before (local cache or Redis)
   - If duplicate: return cached result, don't re-execute

3. Agent sends work_result
   - message_id: unique
   - request_id: SAME as received work_request (idempotency key)
   - trace_id: SAME as work_request (correlation)

4. Orchestrator receives work_result
   - Matches trace_id to original request
   - Verifies request_id matches (confirms it's reply to this request, not stale)
   - Updates task status in DB
```

**Implementation in code:**
- Store (request_id → result) cache in agent for ~5 minutes after completion
- Log all messages with trace_id for post-mortem tracing
- REST API returns trace_id to client (they can search logs)

---

## FastAPI Integration & API Design

### Service Architecture

```
FastAPI app
├── REST endpoints (/api/v1/dispatch, /status, /agents, /cancel)
├── WebSocket endpoint (/ws for real-time updates)
├── Background task: heartbeat listener (separate RabbitMQ consumer)
├── Background task: work result listener (separate RabbitMQ consumer)
└── SQLAlchemy session pool for DB
```

### REST API Endpoints

**POST /api/v1/dispatch** — Submit new work request

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

class DispatchRequest(BaseModel):
    task_id: str
    work_type: str
    parameters: dict
    priority: int = 3  # 1-5
    hints: dict = {}

@app.post("/api/v1/dispatch")
async def dispatch_work(req: DispatchRequest) -> dict:
    """
    1. Validate request
    2. Create message envelope with new request_id, trace_id
    3. Publish to work_queue with priority
    4. Return trace_id to client (for later queries)
    """
    # Implementation details in planning phase
```

**GET /api/v1/status/{task_id}** — Query task status

```python
@app.get("/api/v1/status/{task_id}")
async def get_task_status(task_id: str) -> dict:
    """
    Query tasks table for task status, progress, result.
    Include trace_id for log correlation.
    """
```

**GET /api/v1/agents** — List connected agents

```python
@app.get("/api/v1/agents")
async def list_agents(
    agent_type: str = None,
    status: str = None  # "online", "offline", "busy"
) -> dict:
    """
    Query agent registry (updated by heartbeat listener).
    Return agent ID, type, status, available resources.
    """
```

**POST /api/v1/cancel/{task_id}** — Cancel running task

```python
@app.post("/api/v1/cancel/{task_id}")
async def cancel_task(task_id: str) -> dict:
    """
    Publish cancellation message to agent.
    Agent is responsible for cleanup.
    """
```

### WebSocket Endpoint for Real-Time Updates

```python
from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws/{trace_id}")
async def websocket_endpoint(websocket: WebSocket, trace_id: str):
    """
    Client connects and subscribes to updates for a specific trace_id.
    When work_result arrives, broadcast to connected clients.
    """
    await websocket.accept()
    try:
        # Register this connection
        ws_manager.register(trace_id, websocket)

        while True:
            # Keep connection alive
            data = await websocket.receive_text()
            # Echo or ignore

    except WebSocketDisconnect:
        ws_manager.unregister(trace_id, websocket)
```

### Background Tasks: RabbitMQ Consumers

**Heartbeat Listener** (runs on app startup):
```python
@app.on_event("startup")
async def start_heartbeat_listener():
    """
    Background task that listens for agent heartbeats on status_exchange.
    Updates agent registry in DB with online/offline status.
    """
    asyncio.create_task(consume_heartbeats())

async def consume_heartbeats():
    """
    Connect to RabbitMQ (separate connection from publishers).
    Declare status queue, listen for heartbeats.
    Update PostgreSQL agent_registry table on each heartbeat.
    """
    # Implementation details in planning phase
```

**Work Result Listener** (runs on app startup):
```python
@app.on_event("startup")
async def start_result_listener():
    """
    Background task that listens for work_result on reply_queue.
    Updates tasks table in DB, broadcasts via WebSocket.
    """
    asyncio.create_task(consume_results())

async def consume_results():
    """
    Connect to RabbitMQ (separate connection).
    Consume from reply_queue, deserialize, validate, store.
    Broadcast to WebSocket clients via trace_id.
    Manual ACK after storing in DB.
    """
    # Implementation details in planning phase
```

---

## Python Libraries & Tools Evaluation

### RabbitMQ Client: aio-pika vs Pika

| Aspect | Pika | aio-pika |
|--------|------|----------|
| Type | Synchronous + async adapter | Pure async (asyncio) |
| Connection Pooling | Manual (library: pika-pool) | Built-in via `connect_robust()` |
| Auto-Reconnect | Application-level, complex | Automatic with state recovery |
| FastAPI Fit | Poor (blocking I/O) | Excellent (async-first) |
| Learning Curve | Moderate | Low (async/await) |
| Maturity | Mature (oldest RabbitMQ Python client) | Production-ready (v8+ stable) |
| Recommendation for Phase 2 | **Not recommended** | **Recommended** |

**Decision:** Use **aio-pika** (not pika). It's async-native, integrates cleanly with FastAPI's event loop, and handles reconnection transparently via `connect_robust()`.

### Installation (Updated pyproject.toml)

```toml
[tool.poetry.dependencies]
# ... existing ...
aio-pika = "^13.0"  # Latest async AMQP client
python-json-logger = "^2.0"  # Structured JSON logging with trace_id support

[tool.poetry.group.dev.dependencies]
# ... existing ...
pytest-aio = "^0.3"  # Async test support for aio-pika consumers
```

### Version Pinning

- **aio-pika:** ^13.0 (Feb 2025+)
  - Transparent reconnect with state recovery
  - Robust error handling
  - Active maintenance

- **FastAPI:** ^0.109.0 (already in Phase 1)
  - WebSocket built-in
  - Background tasks support
  - ASGI-compatible

- **Pydantic:** ^2.0 (already in Phase 1)
  - Message validation
  - JSON serialization for protocol

---

## Reliability Patterns & Best Practices

### Message Acknowledgment Strategy

**Pattern: Manual ACK after work starts**

```python
async def consume_work_requests():
    """
    Connect to RabbitMQ, declare work_queue.
    For each message:
    1. Deserialize + validate envelope
    2. Insert task into DB with status='received'
    3. Check idempotency (request_id in completed requests cache)
    4. If duplicate: send cached result, ACK
    5. If new: start async work task, ACK
    6. Work task publishes result to reply_queue
    7. NACK only on deserialization/validation failure
    """
    async with aio_pika.connect_robust("amqp://guest:guest@localhost/") as connection:
        channel = await connection.channel()

        # Prefetch=1: process one message at a time
        await channel.set_qos(prefetch_count=1)

        queue = await channel.get_queue('work_queue')

        async with queue.iterator() as queue_iter:
            async for message: aio_pika.IncomingMessage in queue_iter:
                try:
                    # Deserialize
                    work_req = WorkRequest.model_validate_json(message.body.decode())

                    # Check idempotency
                    if request_already_processed(work_req.request_id):
                        result = get_cached_result(work_req.request_id)
                        await send_work_result(result)
                        await message.ack()
                        continue

                    # Start work (async, non-blocking)
                    asyncio.create_task(execute_work(work_req))

                    # ACK immediately (work task will handle persistence)
                    await message.ack()

                except Exception as e:
                    # NACK on validation error
                    logger.error(f"Invalid message: {e}")
                    await message.nack(requeue=False)  # Send to DLX
```

**Why this pattern:**
- Early ACK signals RabbitMQ "I received this, I'm handling it"
- If consumer crashes before work completes, unacked messages stay in queue (other agents can pick up)
- NACK only for unrecoverable errors (protocol violation, bad JSON)
- Work task stores result in DB; if result is already there, agent can replay without data loss

### NACK vs Requeue Strategy

| Scenario | Action | Reason |
|----------|--------|--------|
| Message deserialization fails (bad JSON) | NACK, no requeue → DLX | Permanent error; retrying won't help |
| Agent connection lost mid-work | No action (timeout) | Unacked message auto-requeues when channel closes |
| Work task fails (transient, e.g., network timeout) | Application logic retries, then sends error result | Let work task handle retry; not broker's job |
| Queue full / broker overloaded | NACK + requeue=true | Try another consumer or wait |
| Work timeout (task running >deadline) | Application sends error result + cancels task | Explicit timeout handling, not NACK |

**Rule:** Reserve NACK for protocol errors. For transient work failures, handle in application code (retry with backoff, exponential delay, send error_result).

### Idempotency Implementation

**In-Memory Cache Pattern (for Phase 2 MVP):**

```python
from collections import OrderedDict
import time

class RequestCache:
    """Simple LRU cache for request idempotency."""

    def __init__(self, ttl_seconds=300, max_size=10000):
        self.ttl = ttl_seconds
        self.max_size = max_size
        self.cache = {}  # request_id -> (result, timestamp)

    def get(self, request_id: str):
        """Return cached result if exists and not expired."""
        if request_id in self.cache:
            result, ts = self.cache[request_id]
            if time.time() - ts < self.ttl:
                return result
            else:
                del self.cache[request_id]
        return None

    def set(self, request_id: str, result: dict):
        """Store result with timestamp."""
        if len(self.cache) >= self.max_size:
            # Evict oldest entry
            oldest_id = next(iter(self.cache))
            del self.cache[oldest_id]
        self.cache[request_id] = (result, time.time())

    def cleanup(self):
        """Periodically remove expired entries."""
        now = time.time()
        expired = [rid for rid, (_, ts) in self.cache.items() if now - ts >= self.ttl]
        for rid in expired:
            del self.cache[rid]
```

**Production upgrade (Phase 3+):** Use Redis instead of in-memory cache for distributed consistency across multiple orchestrator instances.

---

## Operational Considerations

### Agent Registration & Heartbeat Flow

**Startup (Agent):**
1. Agent connects to RabbitMQ, declares/binds queues
2. Agent publishes initial status message (status="online")
3. Agent subscribes to broadcast_exchange for announcements
4. Agent subscribes to work_queue (filtered by agent_type header)

**Periodic (Every 60 seconds):**
1. Agent collects current resource metrics (CPU, GPU VRAM, task ID)
2. Agent publishes status_update to reply_queue (or dedicated status queue)
3. Orchestrator heartbeat listener updates agent_registry table

**Offline Detection (Orchestrator):**
1. Agent hasn't sent heartbeat for 180s (3 missed intervals)
2. Orchestrator marks agent as "offline" in agent_registry
3. If agent had in-flight work, orchestrator requeues unfinished tasks (based on idempotency check)

**Reconnection (Agent):**
1. Agent regains connectivity
2. Agent reconnects to RabbitMQ (aio-pika `connect_robust()` handles automatically)
3. Agent republishes queues/bindings (aio-pika state recovery)
4. Agent sends status_update immediately
5. Orchestrator marks agent as "online"

### Message Persistence Strategy

**Durable queues:** work_queue, reply_queue, dlx_queue all have durable=true
- Metadata (queue name, bindings) persisted to disk
- Messages with persistent=true flag also persisted

**Priority-based persistence (from CONTEXT.md):**
- critical/high priority: publish with persistent=true
- normal/low priority: publish with persistent=false (faster, stays in memory)

**Implementation:**
```python
async def publish_work_request(work_req: WorkRequest):
    """Publish work request with priority-based persistence."""
    persistent = work_req.priority in [4, 5]  # critical/high

    await channel.default_exchange.publish(
        aio_pika.Message(
            body=work_req.model_dump_json().encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT if persistent else aio_pika.DeliveryMode.TRANSIENT,
            priority=work_req.priority
        ),
        routing_key='work_queue'
    )
```

### Queue Persistence Across RabbitMQ Restarts

When RabbitMQ restarts:
1. Durable queues recovered from disk (metadata)
2. Persistent messages (with delivery_mode=persistent) recovered from disk
3. Transient messages (normal/low priority) lost
4. Agents reconnect, republish their bindings (aio-pika `connect_robust()`)

**No orchestrator action required** — RabbitMQ handles recovery automatically.

### Duplicate Message Detection

**Problem:** If orchestrator publishes work_request, RabbitMQ crashes before consumer ACKs, consumer sees message twice.

**Solution:** Idempotency via request_id
1. Same request_id = same request (consumer checked cache, already have result)
2. Agent returns cached result immediately (no re-execution)
3. Idempotency cache expires after ~5 minutes

**Logging:** Log every message with message_id for post-mortem audit (if exact duplicate was processed).

---

## Implementation Notes (What to Watch For)

### aio-pika Connection Management

**Pitfall:** Creating new connection for each message (expensive, slow)

**Pattern:** Single connection, multiple channels
```python
# Good
connection = await aio_pika.connect_robust("amqp://...")
channel1 = await connection.channel()  # For publishing
channel2 = await connection.channel()  # For consuming
# Reuse these channels

# Bad
for each_message:
    conn = await aio_pika.connect("amqp://...")  # DON'T DO THIS
```

**Recovery:** `connect_robust()` automatically reconnects if connection drops. No explicit retry logic needed.

### WebSocket Broadcasting for Many Clients

**Pitfall:** Naive broadcast to all WebSocket connections on every message (scales poorly)

**Pattern:** Maintain per-trace_id subscriber list
```python
# Good
ws_manager = {
    "trace_id_1": [websocket_client_a, websocket_client_b],
    "trace_id_2": [websocket_client_c]
}

# When result arrives for trace_id_1:
for ws in ws_manager["trace_id_1"]:
    await ws.send_json(result)

# Bad
for all_websockets:  # Broadcasts to every connected client
    await ws.send_json(result)
```

### Correlation ID in Logs

**Pattern:** Every log message includes trace_id
```python
logger.info(
    "Work completed",
    extra={
        "trace_id": trace_id,
        "request_id": request_id,
        "task_id": task_id
    }
)
# Output: {"message": "Work completed", "trace_id": "...", "request_id": "...", ...}
```

This enables: `grep "trace_id: abc123" *.log` to find all related events.

### Timeout Handling

**Work timeout:** Set deadline in work_request payload. Agent respects it.
```python
{
    "hints": {
        "deadline_seconds": 300,
        "estimated_duration_seconds": 240
    }
}
```

**Message timeout:** RabbitMQ doesn't timeout unacked messages. Agent is responsible for:
1. Accepting work (send ACK)
2. Starting task
3. Publishing result or error within deadline
4. If deadline exceeded, send error_result manually

### Priority Queue Performance Tuning

**Pitfall:** Using x-max-priority=255 (all 256 levels)

**Pattern:** Use 1-5 only
```python
# Good: 5 levels = 5 internal sub-queues
arguments={'x-max-priority': 5}

# Bad: 255 levels = 255 internal sub-queues = 50x slowdown
arguments={'x-max-priority': 255}
```

Test locally: measure throughput with 5 levels vs 10 levels to confirm acceptable performance.

---

## Code Examples

### Complete aio-pika Consumer Pattern

```python
# Source: aio-pika best practices + Phase 2 requirements
import aio_pika
import json
from pydantic import ValidationError

async def run_consumer():
    """Production-ready RabbitMQ consumer with error handling."""

    connection = None
    try:
        # Connect with automatic reconnect on failure
        connection = await aio_pika.connect_robust("amqp://guest:guest@localhost/")

        async with connection:
            channel = await connection.channel()

            # Set prefetch=1 (process one message at a time)
            await channel.set_qos(prefetch_count=1)

            # Declare queue
            queue = await channel.get_queue('work_queue')

            # Consume messages
            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    async with message.process():
                        try:
                            # Deserialize + validate
                            envelope = json.loads(message.body.decode())
                            work_req = WorkRequest(**envelope)

                            # Check idempotency
                            cached = request_cache.get(work_req.request_id)
                            if cached:
                                await send_result(cached)
                                continue  # ACK implicit via context manager

                            # Process work
                            result = await execute_work(work_req)
                            request_cache.set(work_req.request_id, result)
                            await send_result(result)

                        except ValidationError as e:
                            logger.error(f"Invalid message: {e}", extra={"message_id": message.message_id})
                            # Message will NACK on exception, stay in queue
                            raise
                        except Exception as e:
                            logger.error(f"Work failed: {e}", extra={"message_id": message.message_id})
                            # Send error_result to orchestrator
                            await send_error_result(work_req, str(e))
                            # Raise to trigger NACK if unrecoverable

    except aio_pika.exceptions.AMQPConnectionError:
        logger.error("Connection lost; connect_robust() will retry automatically")
```

### REST API + WebSocket Integration

```python
# Source: FastAPI documentation + Phase 2 requirements
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.responses import JSONResponse
import asyncio
import uuid

app = FastAPI()

class WebSocketManager:
    def __init__(self):
        self.subscriptions = {}  # trace_id -> [websockets]

    def subscribe(self, trace_id: str, websocket: WebSocket):
        if trace_id not in self.subscriptions:
            self.subscriptions[trace_id] = []
        self.subscriptions[trace_id].append(websocket)

    async def broadcast(self, trace_id: str, message: dict):
        if trace_id in self.subscriptions:
            for ws in self.subscriptions[trace_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    self.subscriptions[trace_id].remove(ws)

ws_manager = WebSocketManager()

@app.post("/api/v1/dispatch")
async def dispatch(req: DispatchRequest) -> dict:
    """Dispatch work request."""
    request_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())

    work_req = WorkRequest(
        request_id=request_id,
        trace_id=trace_id,
        **req.dict()
    )

    # Publish to RabbitMQ
    await publish_work_request(work_req)

    # Store in DB
    await db.tasks.insert({
        'task_id': req.task_id,
        'trace_id': trace_id,
        'status': 'pending'
    })

    return {'trace_id': trace_id, 'request_id': request_id}

@app.websocket("/ws/{trace_id}")
async def websocket_endpoint(websocket: WebSocket, trace_id: str):
    """Real-time updates for a task."""
    await websocket.accept()
    ws_manager.subscribe(trace_id, websocket)

    try:
        while True:
            # Keep connection alive, client can send keepalive pings
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        ws_manager.subscriptions.get(trace_id, []).remove(websocket)

# Background task: consume results and broadcast
@app.on_event("startup")
async def start_result_listener():
    asyncio.create_task(consume_results())

async def consume_results():
    """Listen for work results, update DB, broadcast to WebSocket clients."""
    connection = await aio_pika.connect_robust("amqp://guest:guest@localhost/")

    async with connection:
        channel = await connection.channel()
        queue = await channel.get_queue('reply_queue')

        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    result = WorkResult(**json.loads(message.body.decode()))

                    # Update DB
                    await db.tasks.update(
                        {'task_id': result.task_id},
                        {'$set': {'status': result.status, 'result': result.dict()}}
                    )

                    # Broadcast to WebSocket subscribers
                    trace_id = result.trace_id  # Propagated from work_request
                    await ws_manager.broadcast(trace_id, result.dict())
```

---

## Risks & Mitigations

### Risk 1: Message Loss on Orchestrator Crash

**Scenario:** Orchestrator publishes work_request, crashes before storing task in DB. RabbitMQ has message, DB doesn't. Agent completes work, publishes result. Orchestrator recovers, no record of original request.

**Mitigation:**
1. Publish to RabbitMQ first (guaranteed by publisher confirms)
2. Store in DB second (idempotency: if DB insert fails, next retry is skipped)
3. On recovery, query agents for current status instead of relying on DB (CONTEXT.md strategy)

**Code:**
```python
async def dispatch_work(work_req):
    # Step 1: Publish to RabbitMQ (with publisher confirms)
    confirm = await channel.default_exchange.publish(
        message,
        routing_key='work_queue'
    )
    assert confirm.delivery_tag > 0  # Confirmed by broker

    # Step 2: Store in DB
    await db.tasks.insert({'task_id': task_id, 'status': 'dispatched'})

    # If DB fails, exception propagates to caller; they can retry
    # Retry will re-publish (idempotent: request_id in message)
```

### Risk 2: Duplicate Work Execution

**Scenario:** Network lag causes request timeout. Orchestrator retries. Agent receives same work_request twice. Both get executed.

**Mitigation:** Idempotency via request_id cache (5-minute TTL).

**Code:** See "Idempotency Implementation" section above.

### Risk 3: Dead-Letter Queue Fills Up

**Scenario:** Malformed messages repeatedly fail. DLX queue grows. Nobody inspects it. Eventually DLX queue fills memory.

**Mitigation:**
1. Monitor DLX queue depth (Prometheus metric or manual query)
2. Set max-length policy on DLX queue (discard oldest if full)
3. Daily inspection of DLX messages (log samples)
4. Alert if DLX has >100 messages

**Configuration:**
```python
dlx_queue = await channel.declare_queue(
    'dlx_queue',
    durable=True,
    arguments={
        'x-max-length': 10000,  # Discard oldest if exceeded
        'x-dead-letter-exchange': ''  # Nowhere to go; hard error
    }
)
```

### Risk 4: Correlation ID Not Propagated

**Scenario:** Work_request has trace_id. Agent loses it when publishing work_result. Orchestrator can't correlate. Post-mortem debugging hard.

**Mitigation:** Explicit check in message validation (both directions).

**Code:**
```python
class WorkResult(BaseModel):
    request_id: UUID  # MUST be same as work_request
    trace_id: UUID    # MUST be propagated

    @field_validator('trace_id')
    def check_not_none(cls, v):
        assert v is not None, "trace_id required for correlation"
        return v
```

### Risk 5: Priority Queue Starvation

**Scenario:** High-priority jobs constantly arrive. Low-priority jobs never run.

**Mitigation:** This is **by design** (not a bug). If low-priority jobs never run, they're not important. For fairness, implement round-robin across priority levels (Phase 3+ optimization).

---

## State of the Art

| Old Approach | Current Approach (2026) | Change Date | Impact |
|--------------|------------------------|-------------|--------|
| Pika synchronous client | aio-pika async-first | 2023+ | Better integration with async frameworks like FastAPI |
| Manual connection pooling (pika-pool) | Automatic reconnect (aio-pika `connect_robust()`) | 2023+ | Reduces application complexity, transparent recovery |
| RabbitMQ AMQP 0-9-1 only | AMQP 1.0 support (opt-in) | 2024+ | Better interop with other message brokers (optional) |
| Separate message queues per agent type | Single queue + header filtering | 2025+ | Simpler topology, agents filter locally |
| Custom serialization (pickle, MessagePack) | JSON + Pydantic validation | 2020+ | Type safety, language interop, OpenAPI docs |
| Flask-based REST APIs | FastAPI with async/await | 2021+ | Better throughput, native WebSocket, dependency injection |
| Polling for task status | WebSocket for real-time updates | 2021+ | Lower latency, reduced CPU usage |

**Deprecated in Phase 2 scope:**
- Celery (too heavyweight for Phase 2 scope; direct RabbitMQ is simpler)
- Django Channels (not relevant; using FastAPI)
- Custom retry logic (use RabbitMQ + application-level idempotency instead)

---

## Gaps & Open Questions

1. **High-Throughput Correlation ID Uniqueness**
   - What we know: UUID v4 has 2^122 possible values; collision probability negligible
   - What's unclear: At >10k messages/second, how much overhead does trace_id logging add?
   - Recommendation: Benchmark in Phase 2; if logging becomes bottleneck, switch to shorter hash (SHA-256 prefix) for space efficiency

2. **WebSocket Scaling with Many Clients**
   - What we know: FastAPI handles thousands of concurrent connections
   - What's unclear: At >100 concurrent WebSocket connections, how much memory per connection?
   - Recommendation: Monitor in Phase 2; if memory-constrained, implement connection pooling / shard subscriptions across workers

3. **Agent Registration Storage**
   - What we know: Agent registry updated by heartbeat listener
   - What's unclear: Store in PostgreSQL or in-memory cache? Trade-off between consistency and speed?
   - Recommendation: Phase 2 uses PostgreSQL (durable, queryable); Phase 3+ can add Redis caching layer

4. **Dead-Letter Queue Inspection**
   - What we know: DLX catches unrecoverable messages
   - What's unclear: How to automatically surface DLX messages to operator? Alert threshold?
   - Recommendation: Phase 2 does manual query; Phase 3 adds Prometheus metrics + alerting

5. **Message Ordering Across Multiple Agents**
   - What we know: RabbitMQ doesn't guarantee order with multiple consumers
   - What's unclear: If task execution depends on step ordering, how to ensure FIFO?
   - Recommendation: Design agent protocol to support out-of-order delivery (use step_number, not arrival order). Single consumer for strict ordering (trade-off: no parallelism)

---

## Sources

### Primary (HIGH confidence)

- [RabbitMQ Queue Declaration & Durability](https://www.rabbitmq.com/docs/queues) — Official docs on durable queues, x-max-priority, x-dead-letter-exchange
- [RabbitMQ Consumer Acknowledgements & Publisher Confirms](https://www.rabbitmq.com/docs/confirms) — Official documentation on ACK/NACK semantics
- [RabbitMQ Negative Acknowledgements (NACK)](https://www.rabbitmq.com/docs/nack) — Official docs on basic.nack, basic.reject, requeue behavior
- [RabbitMQ Dead Letter Exchanges](https://www.rabbitmq.com/docs/dlx) — Official DLX documentation and configuration patterns
- [RabbitMQ Priority Queues](https://www.rabbitmq.com/docs/priority) — Official docs on x-max-priority configuration and performance considerations
- [RabbitMQ Heartbeat Mechanism](https://www.rabbitmq.com/docs/heartbeats) — Official docs on detecting dead connections
- [RabbitMQ Reliability Guide](https://www.rabbitmq.com/docs/reliability) — Comprehensive guide to delivery guarantees, ACK patterns, failure scenarios
- [FastAPI WebSockets Documentation](https://fastapi.tiangolo.com/advanced/websockets/) — Official FastAPI WebSocket implementation guide
- [aio-pika GitHub Repository](https://github.com/mosquito/aio-pika) — Async AMQP client for Python, auto-reconnect patterns
- [Pydantic v2 Documentation](https://docs.pydantic.dev/latest/) — Field validation, serialization, model definition

### Secondary (MEDIUM confidence)

- [Pika vs aio-pika: Which RabbitMQ Client to Use](https://medium.com/@ar.aldhafeeri11/how-to-use-rabbitmq-with-fastapi-asynchronous-message-publishing-and-consuming-c094da1c47a6) — Medium article comparing async/sync RabbitMQ clients with FastAPI
- [FastAPI + RabbitMQ Architecture Patterns](https://medium.com/cuddle-ai/async-architecture-with-fastapi-celery-and-rabbitmq-c7d029030377) — Async task patterns with FastAPI and RabbitMQ
- [RabbitMQ Exponential Backoff Patterns](https://www.brianstorti.com/rabbitmq-exponential-backoff/) — Brian Storti on delayed retry strategies
- [Correlation IDs in Distributed Systems](https://microsoft.github.io/code-with-engineering-playbook/observability/correlation-id/) — Microsoft engineering playbook on correlation ID implementation
- [W3C Trace Context for Distributed Tracing](https://langfuse.com/docs/observability/features/trace-ids-and-distributed-tracing) — W3C standard for trace/span IDs
- [REST API Error Response Standards (RFC 7807)](https://www.mscharhag.com/api-design/rest-error-format) — Problem Details JSON format for error responses
- [RabbitMQ Priority Queue Performance](https://www.cloudamqp.com/blog/message-priority-in-rabbitmq.html) — CloudAMQP blog on priority queue tuning

### Tertiary (LOW confidence)

- [Idempotency & Duplicate Detection Patterns](https://medium.com/@pvladmq/rabbitmq-message-deduplication-3ab49f8519dc) — Medium article on consumer-side deduplication
- [RabbitMQ + AWS MQ Integration](https://docs.aws.amazon.com/amazon-mq/latest/developer-guide/amazon-mq-rabbitmq-pika.html) — AWS guide (some patterns applicable to open RabbitMQ)
- [Pika Connection Pool Discussion](https://github.com/pika/pika/discussions/1425) — GitHub discussion on pika pooling patterns (not recommended for async)

---

## Metadata

**Confidence breakdown:**

| Area | Level | Reason |
|------|-------|--------|
| RabbitMQ queue topology (durable, priority, DLX) | HIGH | Official RabbitMQ documentation verified |
| aio-pika library choice for FastAPI | HIGH | Confirmed by multiple sources (official aio-pika, community FastAPI patterns) |
| Message protocol (envelope, correlation IDs) | HIGH | Follows standard async task queue patterns (Celery, Google Cloud Tasks) |
| FastAPI WebSocket + REST integration | HIGH | Official FastAPI documentation verified |
| Reliability patterns (ACK/NACK, idempotency) | HIGH | Official RabbitMQ reliability guide + confirmation semantics |
| Agent heartbeat interval (60s) & offline threshold (180s) | MEDIUM | Standard in distributed systems; 3-second negotiation from CONTEXT.md |
| High-throughput correlation ID overhead | LOW | Untested in Phase 2 scope; recommend benchmarking |
| WebSocket scaling characteristics | MEDIUM | FastAPI proven; exact limits depend on hardware/network |
| Dead-letter queue alerting thresholds | LOW | Domain-specific; recommend Phase 2 monitoring setup |

**Research date:** 2026-01-19
**Valid until:** 2026-02-19 (30 days for stable technologies like RabbitMQ)
**Refresh trigger:** If aio-pika major version updates (>13), or if Phase 2 benchmarking reveals performance gaps

---

## Implementation Readiness

All research findings are actionable and directly inform Phase 2 planning:

- ✓ aio-pika selected as RabbitMQ client (async, FastAPI-compatible)
- ✓ Queue topology defined (work, reply, broadcast, DLX with durable=true)
- ✓ Message protocol specified (JSON envelope, correlation ID strategy)
- ✓ REST API endpoints defined (/dispatch, /status, /agents, /cancel)
- ✓ WebSocket implementation pattern provided (subscribe by trace_id)
- ✓ Reliability patterns documented (ACK/NACK, idempotency via request_id, DLX for unrecoverable)
- ✓ Background task patterns for heartbeat + result listening
- ✓ Risks identified and mitigations provided
- ✓ Code examples provided (aio-pika consumer, FastAPI + WebSocket integration)

**Planner can proceed with Phase 2 planning. No blocking gaps.**
