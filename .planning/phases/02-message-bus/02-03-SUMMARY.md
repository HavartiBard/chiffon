# Phase 2 Plan 3: Agent Framework Summary

**Completed:** 2026-01-19
**Duration:** ~55 minutes
**Status:** ✓ All success criteria met

---

## What Was Built

### BaseAgent Class (`src/agents/base.py`)

A robust abstract base class that provides the foundation for all RabbitMQ-connected agents in Chiffon.

**Key Components:**

1. **Connection Management**
   - `async def connect()`: Establishes RabbitMQ connection with automatic reconnection (aio_pika.connect_robust)
   - `async def disconnect()`: Graceful connection cleanup
   - Queue and exchange declaration via `declare_queues()`
   - Prefetch=1 for single-message-at-a-time processing

2. **Heartbeat Messaging (60-second interval)**
   - `async def send_heartbeat()`: Sends StatusUpdate messages to orchestrator
   - Resource metrics: CPU %, memory %, GPU VRAM available/total
   - Includes trace_id and request_id for debugging
   - Graceful degradation if GPU unavailable (nvidia-smi query handles missing GPU)

3. **Work Request Processing**
   - `async def consume_work_requests()`: Main loop listening on work_queue
   - Message validation with protocol version check
   - ACK after message accepted, NACK (no requeue) on validation failure
   - Envelope deserialization with error handling
   - Extracted to `_process_single_message()` helper to reduce complexity

4. **Idempotency Cache**
   - `IdempotencyCache` class: LRU cache with 5-minute TTL
   - Cache key: request_id -> WorkResult
   - Automatic LRU eviction when max_size (1000) exceeded
   - Prevents duplicate work execution on agent reconnection

5. **Error Handling**
   - Validates MessageEnvelope before processing
   - NACKs invalid envelopes (sends to dead-letter exchange)
   - Catches and logs exceptions in heartbeat, work processing, result publishing
   - Doesn't crash on GPU metrics unavailability

6. **Abstract Methods (for subclass implementation)**
   - `async def execute_work(work_request: WorkRequest) -> WorkResult`: Perform actual work
   - `def get_agent_capabilities() -> dict`: Report supported work types

### TestAgent Class (`src/agents/test_agent.py`)

Minimal concrete implementation of BaseAgent for validation and development.

**Work Types Supported:**
- `echo`: Return input as output (immediate, trivial)
- `slow_echo`: Sleep 5 seconds then echo (test timeouts/long work)
- `fail`: Raise exception (test error handling)
- Reports unknown work types as failures (exit_code=1)

**Features:**
- Can be instantiated and run standalone: `poetry run python -m src.agents.test_agent`
- Proper resource tracking in WorkResult
- Structured JSON logging with trace_id

### Integration Tests (`tests/test_agent_framework.py`)

Comprehensive test suite: **32 tests, all passing**

**Test Coverage:**
- Agent initialization and configuration
- Abstract method enforcement
- IdempotencyCache: store/retrieve, LRU behavior, TTL expiration
- Heartbeat message structure with trace_id/request_id
- Work request validation and envelope deserialization
- TestAgent execution for all work types (echo, slow_echo, fail, unknown)
- Message envelope serialization/deserialization roundtrips
- Envelope validation (agent types, message types, priority bounds)
- Resource metrics collection (CPU, memory, GPU graceful degradation)

**Test Organization:**
- 4 tests: Initialization
- 1 test: Abstract methods
- 4 tests: Idempotency cache
- 3 tests: Heartbeat messages
- 2 tests: Work request processing
- 12 tests: TestAgent execution (3 work types × 4 async backends)
- 4 tests: Message envelope validation
- 2 tests: Resource metrics

---

## How It Works

### Agent Startup
```
1. Subclass calls BaseAgent.__init__(agent_id, agent_type, config)
2. Agent calls await agent.run()
3. connect() establishes RabbitMQ connection
4. Start heartbeat_task (background, every 60s)
5. Start consume_work_requests() (blocking main loop)
```

### Work Processing Loop
```
1. Receive message from work_queue
2. Deserialize to MessageEnvelope (validate protocol version, agent types, message type)
3. If invalid: NACK with requeue=False (goes to DLX)
4. If valid: ACK (signal acceptance before executing)
5. Check idempotency cache (request_id -> cached WorkResult)
6. If cached: publish cached result and continue
7. If not cached: execute_work() (subclass override)
8. Cache result, add trace_id/request_id, publish to reply_queue
```

### Heartbeat Loop
```
Every 60 seconds:
1. Collect resource metrics: psutil.cpu_percent(), psutil.virtual_memory().percent
2. Query GPU: nvidia-smi (gracefully handle missing GPU)
3. Create StatusUpdate with agent_id, agent_type, resources
4. Wrap in MessageEnvelope with trace_id, request_id
5. Publish to reply_queue
6. Log with trace_id for debugging
```

### Error Handling
```
Invalid envelope → NACK, no requeue → DLX (dead-letter queue)
Work execution error → Catch exception, log, publish error WorkResult
Heartbeat error → Log, continue (don't crash heartbeat loop)
GPU query error → Return 0 VRAM, continue (graceful degradation)
```

---

## Dependencies Added

- **psutil ^7.2.1**: System resource metrics (CPU %, memory %, process info)
- **types-psutil ^7.2.1.20260116**: Type stubs for mypy compatibility

---

## Protocol Updates

### WorkResult Extended
Added two optional fields for tracking:
- `trace_id: Optional[UUID]`: Set by agent from original request (for debugging)
- `request_id: Optional[UUID]`: Set by agent from original request (for idempotency)

These fields allow orchestrator to correlate results back to requests without additional headers.

---

## Testing Results

```
$ poetry run pytest tests/test_agent_framework.py -v
======================= 32 passed, 12 warnings in 15.18s =======================
```

**Warnings:** Expected deprecation warning from pydantic about `datetime.utcnow()` (scheduled for removal in future Python). Not critical for Phase 2.

**Type Checking:**
```
$ poetry run mypy src/agents/base.py src/agents/test_agent.py
Success: no issues found in 2 source files
```

**Linting:**
```
$ poetry run ruff check src/agents/
Success: no errors
```

---

## Architecture Alignment

**Phase 2 Goal:** "Agents can send/receive messages, orchestrator can query agent status and resources"

**What This Delivers:**
- ✓ Agent connection management (RabbitMQ, graceful reconnection)
- ✓ Message reception and validation (work_queue, ACK/NACK pattern)
- ✓ Message sending (reply_queue, results and status updates)
- ✓ Heartbeat status updates (every 60s, includes resource metrics)
- ✓ Work result correlation (trace_id, request_id preserved)
- ✓ Error handling (invalid messages to DLX, execution errors logged)
- ✓ Extensibility (abstract methods for custom agents)

---

## Next Steps

1. **Phase 2-04:** Orchestrator REST API implementation (dispatch work, query agent status)
2. **Phase 2-05:** Real agents (infra agent wraps Ansible, desktop agent queries GPU/CPU)
3. **Phase 3:** Orchestrator core (planning, scheduling, cost tracking)

---

## Key Design Decisions

1. **Idempotency via Request ID:** Agents cache results by request_id for 5 minutes, enabling safe retries and reconnection recovery

2. **ACK-Before-Execute Pattern:** Agents ACK immediately after validation, before executing work, ensuring RabbitMQ doesn't re-deliver to another agent

3. **No Strict FIFO:** Work order is not guaranteed; agents process messages in any order. Orchestrator handles dependencies via work sequencing.

4. **Resource Metrics in Heartbeat:** CPU, memory, GPU metrics included in status updates every 60s, enabling resource-aware scheduling in Phase 3

5. **Graceful GPU Handling:** nvidia-smi query wrapped with exception handling; missing GPU returns 0 VRAM rather than crashing

6. **Type Safety with Workarounds:** mypy checking enabled; aio_pika's incomplete stubs handled with `# type: ignore` and `Any` types where necessary

---

## Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `src/agents/base.py` | 541 | BaseAgent abstract class |
| `src/agents/test_agent.py` | 160 | TestAgent concrete implementation |
| `tests/test_agent_framework.py` | 424 | Comprehensive integration tests |

## Files Modified

| File | Changes | Purpose |
|------|---------|---------|
| `src/common/protocol.py` | +2 fields | Added trace_id and request_id to WorkResult |
| `pyproject.toml` | +2 deps | Added psutil and types-psutil |

---

## Commits

1. `340b938`: feat(02-03) - BaseAgent class implementation
2. `5f59e7d`: feat(02-03) - TestAgent validation agent
3. `b182db5`: test(02-03) - 32-test integration suite
4. `7595387`: chore(02-03) - Add psutil dependencies

---

## Deviations from Plan

**None** - Plan executed exactly as specified. All must-haves delivered:
- BaseAgent with connection, heartbeat, work processing, idempotency cache
- TestAgent with abstract method implementations
- 32 passing tests (exceeds minimum of 10-15)
- No import errors, no type errors (mypy clean)
- All success criteria met

---

*Plan completed by Claude Haiku 4.5*
*For Phase 2 completion timeline, see STATE.md*
