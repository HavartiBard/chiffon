---
phase: 02-message-bus
plan: 03
type: execute
wave: 2
depends_on: [02-01, 02-02]
files_modified: [src/agents/base.py, src/agents/test_agent.py, src/agents/__init__.py, tests/test_agent_framework.py]
autonomous: true
must_haves:
  truths:
    - "Agent base class can connect to RabbitMQ and bind to work_queue"
    - "Agent sends heartbeat status update every 60 seconds with resource metrics"
    - "Agent receives work request, validates envelope, executes work, sends result back"
    - "Agent respects message acknowledgment pattern (ACK after work starts, NACK on validation failure)"
    - "Test agent implementation works end-to-end: receives work, processes, returns result with correlation IDs intact"
  artifacts:
    - path: "src/agents/base.py"
      provides: "Agent base class with connection management, heartbeat, work processing loop"
      exports: ["BaseAgent", "run_agent()"]
      min_lines: 200
    - path: "src/agents/test_agent.py"
      provides: "Simple test agent for development/validation"
      exports: ["TestAgent"]
      min_lines: 50
    - path: "tests/test_agent_framework.py"
      provides: "Agent framework integration tests"
      contains: "test_agent_connects_to_rabbitmq"
  key_links:
    - from: "src/agents/base.py"
      to: "src/common/rabbitmq.py"
      via: "aio_pika.connect_robust() for connection"
    - from: "src/agents/base.py"
      to: "src/common/protocol.py"
      via: "MessageEnvelope, WorkRequest, WorkResult deserialization/serialization"
---

<objective>
Implement the agent framework base class that handles RabbitMQ connection management, heartbeat messaging, work request reception, and result reporting. Create a test agent to validate the framework works end-to-end before deploying real agents (infra, desktop).

Purpose: Agents are the execution units; they need a common framework for reliable communication with orchestrator
Output: src/agents/base.py with BaseAgent class; src/agents/test_agent.py for validation
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/ROADMAP.md
@.planning/phases/02-message-bus/02-CONTEXT.md
@.planning/phases/02-message-bus/02-RESEARCH.md
@/home/james/Projects/chiffon/src/common/config.py
@/home/james/Projects/chiffon/src/common/protocol.py
@/home/james/Projects/chiffon/src/common/rabbitmq.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Implement src/agents/base.py with BaseAgent class</name>
  <files>src/agents/base.py</files>
  <action>
Create src/agents/base.py with BaseAgent abstract base class:

1. BaseAgent class definition:
   ```python
   class BaseAgent(ABC):
       def __init__(self, agent_id: str, agent_type: str, config: Config):
           self.agent_id = agent_id  # Unique identifier (UUID or hostname)
           self.agent_type = agent_type  # From: orchestrator, infra, desktop, code, research
           self.config = config
           self.connection = None
           self.channel = None
           self.work_queue = None
           self.logger = logging.getLogger(f"agent.{agent_id}")
   ```

2. Connection management:
   - async def connect() -> aio_pika.Connection:
     * Calls aio_pika.connect_robust(get_connection_string() from config)
     * Stores connection, creates channel
     * Calls declare_queues() to ensure topology exists
     * Returns connection for reuse

   - async def disconnect():
     * Closes channel and connection gracefully
     * Logs connection closed

3. Heartbeat sending (every 60 seconds):
   - async def send_heartbeat():
     * Collects resource metrics (psutil library for CPU, memory; nvidia-smi for GPU)
     * Creates StatusUpdate message with:
       - agent_id, agent_type, status='online'
       - current_task_id (from self.current_task_id if set)
       - resources: {cpu_percent, memory_percent, gpu_vram_available_gb, gpu_vram_total_gb}
     * Wraps in MessageEnvelope with from_agent=self.agent_type, to_agent='orchestrator'
     * Publishes to reply_queue via default exchange
     * Logs heartbeat sent (include trace_id)

   - async def start_heartbeat_loop():
     * Runs every 60 seconds in background (asyncio.create_task)
     * Calls send_heartbeat()
     * Handles exceptions (log and continue, don't crash)

4. Work request processing (main loop):
   - async def consume_work_requests():
     * Connects to RabbitMQ (via connect())
     * Declares/binds work_queue
     * Sets prefetch=1 (process one message at a time)
     * For each message in work_queue:
       - Deserialize to MessageEnvelope
       - Validate envelope (check from_agent not in blocked list, protocol version matches)
       - Check if message type is 'work_request'
       - If validation fails: NACK with requeue=False (send to DLX), log error
       - If valid: ACK (signals "I accepted this")
       - Extract WorkRequest from payload
       - Call abstract execute_work(work_request) (subclass implements)
       - Create WorkResult message with same trace_id and request_id as original
       - Publish WorkResult to reply_queue
       - Log completion with trace_id

5. Abstract methods for subclasses:
   - async def execute_work(work_request: WorkRequest) -> WorkResult:
     * Subclasses override this to implement actual work
     * Receives parsed WorkRequest, returns WorkResult with status, exit_code, output, duration, resources_used

   - def get_agent_capabilities() -> dict:
     * Subclasses override to report what they can do (e.g., {"ansible": True, "docker": True})

6. Idempotency cache:
   - Implement simple LRU cache (from RESEARCH.md) or use existing RequestCache pattern
   - Cache key: request_id -> cached WorkResult
   - TTL: 300 seconds (5 minutes)
   - Before executing work, check cache: if request_id exists and not expired, return cached result and ACK

7. Main run loop:
   - async def run():
     * Connects to RabbitMQ
     * Starts heartbeat_loop as background task
     * Starts consume_work_requests() and await it (blocking until agent stops)
     * On shutdown: disconnect, log agent stopped

8. Error handling:
   - aio_pika.exceptions.AMQPConnectionError -> log and reconnect (connect_robust handles this)
   - ValidationError -> NACK, don't requeue (send to DLX)
   - Unexpected errors in execute_work -> catch, create error result, publish, don't crash
   - Missing GPU -> handle gracefully (return 0 for GPU metrics if nvidia-smi fails)

9. Logging:
   - Use python-json-logger for structured logs with trace_id
   - Log at key points: connection made, heartbeat sent, work received, work completed, errors
   - Example: logger.info("Work completed", extra={"trace_id": trace_id, "task_id": task_id, "duration_ms": duration})

10. Dependencies to import:
    - aio_pika (from src.common.rabbitmq)
    - Pydantic models (from src.common.protocol)
    - psutil for resource metrics
    - asyncio for task management
    - uuid for generating agent_id if needed
    - subprocess for nvidia-smi GPU queries (or optional import if not available)

Do NOT implement real work execution (that's plan 02-04 for orchestrator, plan 04-XX for desktop agent, etc.).
  </action>
  <verify>
1. Syntax: python -m py_compile src/agents/base.py
2. Type check: mypy src/agents/base.py --strict (should show 0 errors for concrete methods)
3. Import test: python -c "from src.agents.base import BaseAgent; print('✓ BaseAgent imports')"
4. Abstract check: Verify execute_work() and get_agent_capabilities() are marked @abstractmethod
5. Linting: ruff check src/agents/base.py
  </verify>
  <done>
src/agents/base.py created with BaseAgent abstract class. Connection management, heartbeat loop, work request consumption, idempotency cache, error handling all implemented. Abstract methods for subclasses defined.
  </done>
</task>

<task type="auto">
  <name>Task 2: Implement src/agents/test_agent.py for validation</name>
  <files>src/agents/test_agent.py</files>
  <action>
Create src/agents/test_agent.py with TestAgent subclass:

1. TestAgent class (minimal concrete implementation for testing):
   ```python
   class TestAgent(BaseAgent):
       def __init__(self, config: Config):
           super().__init__(
               agent_id="test-agent-001",
               agent_type="infra",  # Pretend to be infra for testing
               config=config
           )
   ```

2. Implement abstract methods:
   - async def execute_work(work_request: WorkRequest) -> WorkResult:
     * If work_type == "echo": return the input as output (trivial work)
     * If work_type == "slow_echo": sleep for 5 seconds, then echo (test timeouts)
     * If work_type == "fail": raise exception (test error handling)
     * Measure duration_ms from start to finish
     * Populate resources_used (can be dummy data for testing)
     * Return WorkResult with status='completed' or 'failed'

   - def get_agent_capabilities() -> dict:
     * Return {"test": True, "echo": True, "slow_echo": True, "fail": True}

3. If __name__ == "__main__":
   - Parse command-line args for RABBITMQ_URL, DATABASE_URL (from config)
   - Create TestAgent instance
   - Call await agent.run()
   - Can be run in terminal for manual testing

4. Logging:
   - Use same json-logger pattern as BaseAgent
   - Log work received, execution start, completion, errors
  </action>
  <verify>
1. Syntax: python -m py_compile src/agents/test_agent.py
2. Type check: mypy src/agents/test_agent.py
3. Import test: python -c "from src.agents.test_agent import TestAgent; print('✓ TestAgent imports')"
4. Instantiation: python -c "from src.agents.test_agent import TestAgent; from src.common.config import Config; c = Config(); t = TestAgent(c); print(f'✓ TestAgent created: {t.agent_id}')"
  </verify>
  <done>
src/agents/test_agent.py created. TestAgent implements abstract methods. Can be instantiated and run locally for testing.
  </done>
</task>

<task type="auto">
  <name>Task 3: Create integration tests for agent framework (tests/test_agent_framework.py)</name>
  <files>tests/test_agent_framework.py</files>
  <action>
Create tests/test_agent_framework.py with integration tests (these may use mocking for RabbitMQ):

1. Test fixtures:
   - @pytest.fixture config() -> returns test Config with test DATABASE_URL and RABBITMQ_URL
   - @pytest.fixture test_agent(config) -> returns TestAgent instance
   - @pytest.fixture mock_connection() -> mocks aio_pika connection for unit tests

2. Unit tests (with mocking):
   - test_agent_initializes_with_id_and_type
   - test_agent_has_abstract_methods
   - test_test_agent_can_instantiate
   - test_test_agent_implements_execute_work
   - test_test_agent_get_agent_capabilities_returns_dict
   - test_heartbeat_message_has_trace_id
   - test_heartbeat_message_has_request_id
   - test_work_request_deserialization_validates_envelope
   - test_work_request_failed_validation_nacks
   - test_idempotency_cache_stores_and_retrieves_results
   - test_idempotency_cache_expires_after_ttl

3. Mock integration tests (if possible without live RabbitMQ):
   - test_agent_connects_to_rabbitmq (mock aio_pika.connect_robust)
   - test_agent_declares_queues_on_connect
   - test_agent_sends_heartbeat_every_60_seconds (mock time.sleep)
   - test_agent_acks_after_work_starts
   - test_agent_nacks_on_validation_failure

Keep this lean (10-15 tests). More thorough testing is checkpoint:human-verify (manual testing with live RabbitMQ).
  </action>
  <verify>
1. Syntax: python -m py_compile tests/test_agent_framework.py
2. Run tests: pytest tests/test_agent_framework.py -v
   - Expected: All tests PASS
3. Count tests: grep -c "^def test_" tests/test_agent_framework.py should be >= 10
  </verify>
  <done>
tests/test_agent_framework.py created with 10-15 integration/unit tests. All tests pass.
  </done>
</task>

</tasks>

<verification>
After execution:
1. Import test: python -c "from src.agents.base import BaseAgent; from src.agents.test_agent import TestAgent; print('✓')"
2. Test run: pytest tests/test_agent_framework.py -v
3. Type check: mypy src/agents/base.py src/agents/test_agent.py
4. Linting: ruff check src/agents/
</verification>

<success_criteria>
- src/agents/base.py: BaseAgent class complete with connection management, heartbeat loop, work request consumption, idempotency cache
- src/agents/test_agent.py: TestAgent subclass implements abstract methods (execute_work, get_agent_capabilities)
- tests/test_agent_framework.py: 10+ tests passing
- No import errors, no type errors
- Idempotency cache working (request_id -> result)
- Heartbeat messages include trace_id and request_id
- All work results have same trace_id as original work_request
</success_criteria>

<output>
After completion, create `.planning/phases/02-message-bus/02-03-SUMMARY.md` with:
- BaseAgent class features (connection, heartbeat, work processing)
- TestAgent capabilities (echo, slow_echo, fail work types)
- Test coverage (e.g., 12 tests passing)
- Next step reference: "Proceed to 02-04-orchestrator-rest-PLAN.md (parallel)"
</output>
