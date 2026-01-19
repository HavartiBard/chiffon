---
phase: 02-message-bus
plan: 04
type: execute
wave: 2
depends_on: [02-01, 02-02]
files_modified: [src/orchestrator/main.py, src/orchestrator/api.py, src/orchestrator/service.py, tests/test_orchestrator_api.py]
autonomous: true
must_haves:
  truths:
    - "POST /api/v1/dispatch accepts work request and returns trace_id and request_id"
    - "GET /api/v1/status/{task_id} returns current task status and progress"
    - "GET /api/v1/agents returns list of connected agents with resource status"
    - "POST /api/v1/cancel/{task_id} cancels in-flight task"
    - "All REST responses use consistent JSON format; errors include error_code and message"
  artifacts:
    - path: "src/orchestrator/main.py"
      provides: "FastAPI app with lifespan, startup/shutdown, endpoints"
      exports: ["app"]
    - path: "src/orchestrator/api.py"
      provides: "REST endpoints for dispatch, status, agents, cancel"
      exports: ["router"]
      min_lines: 150
    - path: "src/orchestrator/service.py"
      provides: "Orchestrator business logic (task management, agent registry)"
      exports: ["OrchestratorService"]
      min_lines: 100
    - path: "tests/test_orchestrator_api.py"
      provides: "API endpoint tests with mocked RabbitMQ"
      contains: "test_dispatch_endpoint"
  key_links:
    - from: "src/orchestrator/api.py"
      to: "src/common/protocol.py"
      via: "MessageEnvelope, WorkRequest serialization"
    - from: "src/orchestrator/service.py"
      to: "src/common/rabbitmq.py"
      via: "Publishing to work_queue and consuming from reply_queue"
---

<objective>
Implement the orchestrator REST API with endpoints for dispatching work, querying task status, listing agents, and canceling tasks. Establish the orchestrator as the central control point for agent coordination.

Purpose: Users/callers interact with orchestrator via REST API; orchestrator internally routes to agents via RabbitMQ
Output: src/orchestrator/api.py with 4 REST endpoints; src/orchestrator/service.py with OrchestratorService
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
@/home/james/Projects/chiffon/src/orchestrator/main.py
@/home/james/Projects/chiffon/src/common/database.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create src/orchestrator/service.py with OrchestratorService</name>
  <files>src/orchestrator/service.py</files>
  <action>
Create src/orchestrator/service.py with OrchestratorService class:

1. OrchestratorService initialization:
   ```python
   class OrchestratorService:
       def __init__(self, config: Config, db_session):
           self.config = config
           self.db = db_session
           self.connection = None
           self.channel = None
           self.request_cache = RequestCache(ttl_seconds=300)  # From RESEARCH.md
           self.logger = logging.getLogger("orchestrator.service")
           self.ws_manager = None  # For WebSocket broadcasting (set by main.py)
   ```

2. Async initialization and cleanup:
   - async def connect():
     * Calls aio_pika.connect_robust(RABBITMQ_URL)
     * Creates channel
     * Calls declare_queues() to ensure RabbitMQ topology exists
     * Stores connection for reuse

   - async def disconnect():
     * Closes channel and connection gracefully

3. Dispatch work endpoint service logic:
   - async def dispatch_work(task_id: UUID, work_type: str, parameters: dict, priority: int = 3):
     * Validate priority is 1-5
     * Generate request_id (for idempotency)
     * Generate trace_id (for correlation)
     * Create WorkRequest pydantic model
     * Wrap in MessageEnvelope with from_agent='orchestrator', to_agent=self._determine_agent_type(work_type)
     * Publish to work_queue with priority
     * Store task in PostgreSQL with: task_id, trace_id, request_id, work_type, status='pending', created_at
     * Return {trace_id, request_id, task_id}

   - def _determine_agent_type(work_type: str) -> str:
     * Map work_type to agent_type (e.g., "ansible" -> "infra", "metrics" -> "desktop")
     * If no mapping: raise ValueError

4. Status query endpoint service logic:
   - async def get_task_status(task_id: UUID) -> dict:
     * Query PostgreSQL tasks table for task_id
     * If not found: raise HTTPException(404)
     * Return {task_id, status, progress, output, error_message, result, trace_id}

5. Agent registry and listing:
   - async def register_agent(agent_id: UUID, agent_type: str, status: str, resources: dict):
     * Called by heartbeat listener
     * Upsert into agent_registry table (agent_id, agent_type, status, resources, last_heartbeat_at)

   - async def list_agents(agent_type: str = None, status: str = None) -> list[dict]:
     * Query agent_registry table
     * Filter by agent_type if provided
     * Filter by status if provided
     * Return list of {agent_id, agent_type, status, resources, last_heartbeat_at}

   - async def is_agent_online(agent_id: UUID) -> bool:
     * Query last_heartbeat_at
     * Return True if within last 180 seconds (3 missed heartbeats @ 60s interval)
     * Otherwise mark as offline and return False

6. Cancel work:
   - async def cancel_task(task_id: UUID):
     * Query task status
     * If status not in ['pending', 'running']: raise ValueError
     * Publish cancellation message to agent (work_type="cancel", parameters={task_id})
     * Update task status to 'cancelled' in DB
     * Return {task_id, status: 'cancelled'}

7. Work result handling (called by result listener background task):
   - async def handle_work_result(work_result: WorkResult):
     * Query cache: request_id -> result (avoid duplicates)
     * If cached: log and return (duplicate result)
     * If new: store result in task row (status, output, error_message, exit_code, duration_ms)
     * Broadcast to WebSocket subscribers (trace_id)
     * Clear request from idempotency cache after successful storage

8. Error handling:
   - Connection errors: log, reconnect (aio-pika handles via connect_robust)
   - Missing agent type: raise ValueError with helpful message
   - Task not found: raise HTTPException(404)
   - Invalid priority: raise ValueError

9. Logging:
   - Use json-logger with trace_id, request_id, task_id in extra fields
   - Log at key points: dispatch, status query, agent register, cancel, result received
  </action>
  <verify>
1. Syntax: python -m py_compile src/orchestrator/service.py
2. Type check: mypy src/orchestrator/service.py
3. Import test: python -c "from src.orchestrator.service import OrchestratorService; print('✓')"
4. Linting: ruff check src/orchestrator/service.py
  </verify>
  <done>
src/orchestrator/service.py created with OrchestratorService. Dispatch, status, agent registry, and cancel logic implemented.
  </done>
</task>

<task type="auto">
  <name>Task 2: Create src/orchestrator/api.py with REST endpoints</name>
  <files>src/orchestrator/api.py</files>
  <action>
Create src/orchestrator/api.py with FastAPI router and Pydantic request/response models:

1. Pydantic models for REST API:
   ```python
   class DispatchRequest(BaseModel):
       task_id: UUID = Field(description="Task ID")
       work_type: str = Field(description="Type of work (e.g., ansible, shell_script)")
       parameters: dict = Field(default_factory=dict, description="Work parameters")
       priority: int = Field(default=3, ge=1, le=5, description="Priority 1-5")

   class DispatchResponse(BaseModel):
       trace_id: UUID = Field(description="Trace ID for correlation")
       request_id: UUID = Field(description="Request ID for idempotency")
       task_id: UUID = Field(description="Task ID")
       status: str = Field(default="pending", description="Initial status")

   class TaskStatus(BaseModel):
       task_id: UUID
       status: str  # pending, running, completed, failed, cancelled
       progress: str = Field(default="", description="Human-readable progress")
       output: str = Field(default="", description="Work output")
       error_message: Optional[str] = None
       exit_code: Optional[int] = None
       duration_ms: Optional[int] = None
       trace_id: UUID
       created_at: datetime
       updated_at: datetime

   class Agent(BaseModel):
       agent_id: UUID
       agent_type: str
       status: str  # online, offline, busy
       resources: dict  # {cpu_percent, memory_percent, gpu_vram_available_gb, ...}
       last_heartbeat_at: datetime

   class ErrorResponse(BaseModel):
       error_code: int = Field(ge=1000, le=9999)
       error_message: str
       trace_id: Optional[UUID] = None
   ```

2. Create router:
   ```python
   router = APIRouter(prefix="/api/v1", tags=["orchestration"])
   ```

3. POST /api/v1/dispatch:
   - Accept DispatchRequest (task_id, work_type, parameters, priority)
   - Call orchestrator_service.dispatch_work()
   - Return DispatchResponse (trace_id, request_id, task_id, status)
   - On error: return ErrorResponse with error_code (1001 for invalid work_type, etc.)
   - HTTP status: 200 (success), 400 (bad request), 500 (server error)

4. GET /api/v1/status/{task_id}:
   - Path parameter: task_id (UUID)
   - Call orchestrator_service.get_task_status()
   - Return TaskStatus
   - On error: return ErrorResponse with error_code (2001 for task not found)
   - HTTP status: 200 (success), 404 (not found), 500 (server error)

5. GET /api/v1/agents:
   - Query parameters: agent_type (optional), status (optional)
   - Call orchestrator_service.list_agents()
   - Return list of Agent
   - HTTP status: 200

6. POST /api/v1/cancel/{task_id}:
   - Path parameter: task_id (UUID)
   - Call orchestrator_service.cancel_task()
   - Return {task_id, status: 'cancelled'}
   - On error: return ErrorResponse with error_code (2002 for invalid state)
   - HTTP status: 200 (success), 400 (bad request), 404 (not found), 500 (server error)

7. Error handling:
   - Use FastAPI HTTPException for standard errors
   - Return ErrorResponse for all errors with trace_id for correlation
   - Example:
     ```python
     try:
         result = await orchestrator_service.dispatch_work(...)
     except ValueError as e:
         logger.error(f"Invalid work type: {e}", extra={"trace_id": trace_id})
         return ErrorResponse(error_code=1001, error_message=str(e), trace_id=trace_id)
     ```

8. Dependency injection:
   - Use FastAPI Depends() to inject orchestrator_service
   - In main.py: create orchestrator_service as app state, inject via dependency

9. Logging:
   - Log all API calls with trace_id (generate new one if not in request)
   - Log response status and duration

10. Response formatting:
    - All responses are JSON with snake_case fields
    - Datetimes are ISO 8601 strings
    - UUIDs are strings

Size estimate: ~200-250 lines of code.
  </action>
  <verify>
1. Syntax: python -m py_compile src/orchestrator/api.py
2. Type check: mypy src/orchestrator/api.py
3. Import test: python -c "from src.orchestrator.api import router; print('✓')"
4. Linting: ruff check src/orchestrator/api.py
5. Pydantic models: python -c "from src.orchestrator.api import DispatchRequest; r = DispatchRequest(task_id='...', work_type='test'); print(r.model_dump_json())"
  </verify>
  <done>
src/orchestrator/api.py created with router and 4 endpoints (/dispatch, /status/{task_id}, /agents, /cancel/{task_id}). All models properly typed.
  </done>
</task>

<task type="auto">
  <name>Task 3: Update src/orchestrator/main.py and create background tasks for RabbitMQ listening</name>
  <files>src/orchestrator/main.py</files>
  <action>
Update src/orchestrator/main.py to:

1. Add imports:
   - from src.orchestrator.api import router
   - from src.orchestrator.service import OrchestratorService
   - from src.common.rabbitmq import declare_queues
   - import aio_pika

2. Include router in FastAPI app:
   ```python
   app.include_router(router)
   ```

3. Update lifespan context manager to:
   - Startup:
     * Create orchestrator_service and store in app.state
     * Call orchestrator_service.connect() (initialize RabbitMQ connection)
     * Start background task: consume_heartbeats()
     * Start background task: consume_work_results()

   - Shutdown:
     * Call orchestrator_service.disconnect()
     * Cancel background tasks

4. Implement background tasks:
   - async def consume_heartbeats():
     * Connect to RabbitMQ (separate connection from publishers)
     * Declare status queue (or reuse reply_queue with dedicated consumer)
     * For each heartbeat message:
       - Deserialize StatusUpdate from MessageEnvelope
       - Call orchestrator_service.register_agent() with agent_id, agent_type, status, resources
       - ACK message

   - async def consume_work_results():
     * Connect to RabbitMQ (separate connection)
     * Declare reply_queue consumer
     * For each work_result message:
       - Deserialize WorkResult from MessageEnvelope
       - Call orchestrator_service.handle_work_result() to store in DB and broadcast via WebSocket
       - ACK message

5. Dependency injection for OrchestratorService:
   ```python
   from fastapi import Depends

   def get_orchestrator_service() -> OrchestratorService:
       return app.state.orchestrator_service

   # In api.py endpoints:
   @router.post("/api/v1/dispatch")
   async def dispatch(req: DispatchRequest, service: OrchestratorService = Depends(get_orchestrator_service)):
       ...
   ```

6. Add WebSocket support (for real-time updates, Phase 2-05 focuses on this):
   - Store WebSocket manager in app.state
   - Reference from service for broadcasting

7. Health check endpoint:
   - Already exists (/health)
   - Update to include RabbitMQ and database health

8. Error handling:
   - If orchestrator_service.connect() fails: log and exit (don't start app)
   - If background tasks fail: log and restart (exponential backoff)

Keep updates minimal to preserve existing /health endpoint and app structure.
  </action>
  <verify>
1. Syntax: python -m py_compile src/orchestrator/main.py
2. Import test: python -c "from src.orchestrator.main import app; print('✓')"
3. Linting: ruff check src/orchestrator/main.py
4. Type check: mypy src/orchestrator/main.py
5. Check include_router: grep -n "include_router" src/orchestrator/main.py should show the router included
  </verify>
  <done>
src/orchestrator/main.py updated with router inclusion, background tasks (heartbeat and result listeners), and dependency injection.
  </done>
</task>

<task type="auto">
  <name>Task 4: Create API endpoint tests (tests/test_orchestrator_api.py)</name>
  <files>tests/test_orchestrator_api.py</files>
  <action>
Create tests/test_orchestrator_api.py with endpoint tests:

1. Test fixtures:
   - @pytest.fixture client() -> TestClient(app) for testing endpoints
   - @pytest.fixture mock_orchestrator_service() -> mocked OrchestratorService
   - Mock aio_pika.connect_robust() to prevent actual RabbitMQ calls

2. POST /api/v1/dispatch tests (5 tests):
   - test_dispatch_accepts_valid_request
   - test_dispatch_returns_trace_id_and_request_id
   - test_dispatch_requires_task_id
   - test_dispatch_requires_work_type
   - test_dispatch_validates_priority_range_1_to_5

3. GET /api/v1/status/{task_id} tests (4 tests):
   - test_status_returns_task_info
   - test_status_returns_404_for_missing_task
   - test_status_returns_trace_id_for_correlation
   - test_status_returns_timestamps

4. GET /api/v1/agents tests (3 tests):
   - test_list_agents_returns_all_agents
   - test_list_agents_filters_by_agent_type
   - test_list_agents_filters_by_status

5. POST /api/v1/cancel/{task_id} tests (3 tests):
   - test_cancel_cancels_pending_task
   - test_cancel_rejects_completed_task
   - test_cancel_returns_404_for_missing_task

6. Error response tests (3 tests):
   - test_error_response_has_error_code
   - test_error_response_has_error_message
   - test_error_response_includes_trace_id

Use FastAPI TestClient (from fastapi.testclient import TestClient).
Mock orchestrator_service using unittest.mock.patch().
Keep tests focused on API contract, not business logic (business logic tested in integration tests).

Total: 18+ tests.
  </action>
  <verify>
1. Syntax: python -m py_compile tests/test_orchestrator_api.py
2. Run tests: pytest tests/test_orchestrator_api.py -v
   - Expected: All tests PASS
3. Count tests: grep -c "^def test_" tests/test_orchestrator_api.py should be >= 18
4. Coverage: pytest tests/test_orchestrator_api.py --cov=src.orchestrator.api --cov-report=term-missing
  </verify>
  <done>
tests/test_orchestrator_api.py created with 18+ tests covering all 4 endpoints. All tests pass.
  </done>
</task>

</tasks>

<verification>
After execution:
1. Import test: python -c "from src.orchestrator.main import app; from src.orchestrator.api import router; from src.orchestrator.service import OrchestratorService; print('✓')"
2. API test run: pytest tests/test_orchestrator_api.py -v
3. Type check: mypy src/orchestrator/main.py src/orchestrator/service.py src/orchestrator/api.py
4. Linting: ruff check src/orchestrator/
5. OpenAPI spec: app should have Swagger docs at /docs and /redoc
</verification>

<success_criteria>
- src/orchestrator/service.py: OrchestratorService with dispatch_work, get_task_status, list_agents, cancel_task, handle_work_result methods
- src/orchestrator/api.py: Router with 4 endpoints (POST /dispatch, GET /status/{task_id}, GET /agents, POST /cancel/{task_id})
- src/orchestrator/main.py: Updated with router inclusion, background tasks, dependency injection
- tests/test_orchestrator_api.py: 18+ tests, all passing
- No import errors, no type errors
- All REST responses use consistent JSON format with error_code and message
- Trace_id propagation in all API responses for correlation
</success_criteria>

<output>
After completion, create `.planning/phases/02-message-bus/02-04-SUMMARY.md` with:
- API endpoints implemented (list 4)
- OrchestratorService features (dispatch, status, agents, cancel)
- Background tasks (heartbeat listener, result listener)
- Test coverage (e.g., 20 tests passing)
- Next step reference: "Proceed to 02-05-websocket-PLAN.md"
</output>
