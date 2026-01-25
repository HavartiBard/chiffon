---
phase: 03-orchestrator-core
plan: 05
type: execute
wave: 2
depends_on: ["03-01", "03-02", "03-03", "03-04"]
files_modified:
  - src/orchestrator/service.py
  - src/orchestrator/api.py
  - tests/test_orchestrator_e2e.py
autonomous: true
must_haves:
  truths:
    - "User submits request via REST API, orchestrator parses and returns plan"
    - "Plan presented to user for approval (pending_approval status)"
    - "User approves plan, orchestrator dispatches work to agents via RabbitMQ"
    - "Work dispatch uses router to select best agent, logged to routing_decisions"
    - "Full E2E workflow: request → parse → plan → approve → route → dispatch works end-to-end"
  artifacts:
    - path: "src/orchestrator/service.py"
      provides: "OrchestratorService with request handling, plan generation, approval workflow"
      exports: ["OrchestratorService"]
    - path: "src/orchestrator/api.py"
      provides: "REST API endpoints for /request, /plan, /approve, /status"
      exports: ["router", "submit_request", "approve_plan", "get_plan_status"]
    - path: "tests/test_orchestrator_e2e.py"
      provides: "E2E integration tests covering full workflow"
      exports: ["TestOrchhestratorE2E", "TestApprovalWorkflow", "TestDispatch"]
  key_links:
    - from: "OrchestratorService"
      to: "RequestDecomposer"
      via: "submits requests to decomposer.decompose()"
      pattern: "await.*decomposer.decompose"
    - from: "OrchestratorService"
      to: "WorkPlanner"
      via: "generates plan from decomposed request via planner.generate_plan()"
      pattern: "await.*planner.generate_plan"
    - from: "OrchestratorService"
      to: "AgentRouter"
      via: "dispatches tasks via router.route_task() and dispatch_with_retry()"
      pattern: "await.*router.*route_task|dispatch_with_retry"
    - from: "OrchestratorService"
      to: "ExternalAIFallback"
      via: "checks fallback decision before executing complex tasks"
      pattern: "await.*fallback.should_use_external_ai"
    - from: "REST API"
      to: "RabbitMQ"
      via: "dispatches work messages to agent queues"
      pattern: "channel.default_exchange.publish.*routing_key"
---

<objective>
Build the orchestrator service integration layer that ties together all Phase 3 modules (NLU, planner, router, fallback) into a unified REST API and implements the complete request → plan → approval → dispatch workflow.

Purpose: Create the orchestrator's public API and internal orchestration logic, enabling users to submit natural language requests, review generated plans, approve execution, and dispatch work to agents. Integrate all Phase 3 components into a cohesive orchestration engine.

Output: Updated OrchestratorService with request handling and approval workflow, REST API endpoints for user interaction, and comprehensive E2E integration tests validating the complete "Deploy Kuma" workflow.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/03-orchestrator-core/03-CONTEXT.md
@.planning/phases/03-orchestrator-core/03-RESEARCH.md

@.planning/phases/03-orchestrator-core/03-01-SUMMARY.md
@.planning/phases/03-orchestrator-core/03-02-SUMMARY.md
@.planning/phases/03-orchestrator-core/03-03-SUMMARY.md
@.planning/phases/03-orchestrator-core/03-04-SUMMARY.md
@src/orchestrator/service.py
@src/orchestrator/api.py
@src/common/protocol.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Extend OrchestratorService with request handling and approval workflow</name>
  <files>src/orchestrator/service.py</files>
  <action>
Extend src/orchestrator/service.py OrchestratorService class with new methods for request handling and plan approval.

Add instance variables to __init__:
  - decomposer: RequestDecomposer (for parsing requests)
  - planner: WorkPlanner (for generating plans)
  - router: AgentRouter (for agent selection)
  - fallback: ExternalAIFallback (for quota/complexity checks)

New method: `async def submit_request(request_text: str, user_id: str) -> dict`
  1. Validate request (not empty, reasonable length <10000 chars)
  2. Create request_id (UUID4)
  3. Log request submission
  4. Call decomposer.decompose(request_text)
  5. If decomposition successful:
     - Return {request_id, status="parsing_complete", decomposed_request}
  6. If decomposition failed (ambiguities, out_of_scope):
     - Return {request_id, status="requires_clarification", ambiguities, out_of_scope}
  7. Store request in Task table (request_text, status="pending", request_id=uuid)

New method: `async def generate_plan(request_id: UUID) -> dict`
  1. Retrieve decomposed request (from decomposer cache or Task record)
  2. Get available resources from agent pool
  3. Call planner.generate_plan(decomposed, available_resources)
  4. Check fallback decision via fallback.should_use_external_ai(plan)
  5. Update plan.will_use_external_ai based on fallback decision
  6. Save plan to database (new WorkPlanRecord table or Task record)
  7. Return {plan_id, tasks, human_readable_summary, status="pending_approval"}

New method: `async def approve_plan(plan_id: UUID, user_approval: bool = True) -> dict`
  1. Validate plan exists
  2. If user_approval == True:
     - Update plan status → "approved"
     - Timestamp approval time
     - Begin execution: call dispatch_plan()
     - Return {plan_id, status="approved", dispatch_started=True}
  3. If user_approval == False:
     - Update plan status → "rejected"
     - Log rejection reason
     - Return {plan_id, status="rejected"}

New method: `async def dispatch_plan(plan_id: UUID) -> dict`
  1. Retrieve approved plan from database
  2. For each task in plan.tasks (in order):
     - Route task to agent: router.dispatch_with_retry(task)
     - Dispatch work via RabbitMQ (reuse Phase 2 dispatch logic)
     - Create ExecutionLog entry with step_number, agent_id, work_type
     - On dispatch success: return {task_id, status="dispatched", agent_id}
     - On dispatch failure (after retries): return {task_id, status="dispatch_failed", error}
  3. Update plan status → "executing"
  4. Return {plan_id, status="executing", dispatched_tasks}

New method: `async def get_plan_status(plan_id: UUID) -> dict`
  1. Retrieve plan from database
  2. Retrieve all ExecutionLog entries for plan's tasks
  3. Summarize execution progress (dispatched/executing/completed/failed counts)
  4. Return {plan_id, status, tasks_summary, execution_logs}

Helper: `def _validate_request(request_text: str) -> bool`
  - Check not empty, <10000 chars
  - Raise ValueError if invalid

Helper: `async def _get_available_resources() -> dict`
  - Query agent pool for available resources
  - Aggregate GPU VRAM, CPU cores from online agents
  - Return {gpu_vram_mb, cpu_cores}

Error handling:
  - If request parsing fails: return error response with reason
  - If plan generation fails: log error, return error response
  - If dispatch fails: retry (via router.dispatch_with_retry)
  - If all dispatch retries fail: mark task as failed, continue with next task
  - Never throw exceptions; always return structured error responses

Logging:
  - Info on each step transition (submit → generate → approve → dispatch)
  - Warning on failures (parsing failed, dispatch failed)
  - Audit log of all user interactions (request submission, approval, rejection)
  </action>
  <verify>
Test import: `python -c "from src.orchestrator.service import OrchestratorService; print('Extended successfully')"`.

Test request submission (manual async test):
```python
import asyncio
from src.orchestrator.service import OrchestratorService

async def test():
    orchestrator = OrchestratorService(db_session, config)
    # Initialize components (decomposer, planner, router, fallback)

    # Test 1: Submit request
    result = await orchestrator.submit_request("Deploy Kuma and add portals to config", "user123")
    assert result["request_id"]
    assert result["status"] in ["parsing_complete", "requires_clarification"]
    print("Test 1 passed: Request submitted")

    # Test 2: Generate plan
    request_id = result["request_id"]
    plan_result = await orchestrator.generate_plan(request_id)
    assert plan_result["plan_id"]
    assert len(plan_result["tasks"]) >= 1
    assert "human_readable_summary" in plan_result
    print("Test 2 passed: Plan generated")

    # Test 3: Approve plan
    plan_id = plan_result["plan_id"]
    approval_result = await orchestrator.approve_plan(plan_id, user_approval=True)
    assert approval_result["status"] == "approved"
    print("Test 3 passed: Plan approved")

asyncio.run(test())
```

Should show full workflow: request → plan → approval.
  </verify>
  <done>
OrchestratorService extended with submit_request(), generate_plan(), approve_plan(), dispatch_plan(), and get_plan_status() methods. Full request → plan → approval → dispatch workflow implemented. Error handling and logging in place.
  </done>
</task>

<task type="auto">
  <name>Task 2: Create REST API endpoints in src/orchestrator/api.py</name>
  <files>src/orchestrator/api.py</files>
  <action>
Extend src/orchestrator/api.py with new REST API endpoints for request submission, plan approval, and status queries.

Using FastAPI, add these endpoints:

**POST /api/v1/request** - Submit a natural language request
  Request body: {request: str, user_id: str}
  Response: {request_id: UUID, status: str, decomposed_request?: DecomposedRequest, ambiguities?: list, out_of_scope?: list}
  Status codes: 200 OK, 400 Bad Request (invalid input), 500 Internal Server Error

**GET /api/v1/plan/{request_id}** - Get generated plan for a request
  Response: {plan_id: UUID, request_id: UUID, tasks: list[WorkTask], human_readable_summary: str, status: str, complexity_level: str, will_use_external_ai: bool}
  Status codes: 200 OK, 404 Not Found (request doesn't exist), 500 Server Error

**POST /api/v1/plan/{plan_id}/approve** - Approve a plan for execution
  Request body: {approved: bool, user_id: str, notes?: str}
  Response: {plan_id: UUID, status: str, dispatch_started?: bool, error?: str}
  Status codes: 200 OK, 404 Not Found, 409 Conflict (plan already approved), 500 Server Error

**GET /api/v1/plan/{plan_id}/status** - Get execution status of a plan
  Response: {plan_id: UUID, status: str, tasks: list[{task_id, status, agent_id}], execution_logs: list, summary: {dispatched: int, executing: int, completed: int, failed: int}}
  Status codes: 200 OK, 404 Not Found, 500 Server Error

**GET /api/v1/request/{request_id}** - Get status of a submitted request
  Response: {request_id: UUID, status: str, request_text: str, created_at: datetime, plan_id?: UUID}
  Status codes: 200 OK, 404 Not Found, 500 Server Error

Implementation details:
  - Use FastAPI dependency injection to provide OrchestratorService instance
  - Use Pydantic models for request/response validation
  - Add comprehensive error handling (try/except with appropriate status codes)
  - Add request validation (not empty, reasonable length)
  - Add logging for each endpoint (INFO on success, WARNING on failure)
  - Add OpenAPI/Swagger documentation via docstrings
  - Use meaningful HTTP status codes (200, 400, 404, 409, 500)

Example endpoint implementation:
```python
@router.post("/api/v1/request", response_model=dict)
async def submit_request(
    request: dict,
    orchestrator: OrchestratorService = Depends(get_orchestrator_service)
) -> dict:
    """Submit a natural language request to the orchestrator.

    Request body:
        - request (str): Natural language request (e.g., "Deploy Kuma to homelab")
        - user_id (str): User submitting the request

    Returns:
        - request_id (UUID): Unique request identifier
        - status (str): parsing_complete|requires_clarification
        - decomposed_request (optional): If parsing succeeded
        - ambiguities (optional): If clarification needed
    """
    try:
        result = await orchestrator.submit_request(
            request.get("request"),
            request.get("user_id")
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Request submission failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
```

All endpoints follow this pattern: validate input → call service → return response or error.
  </action>
  <verify>
Test endpoints using FastAPI test client:
```python
from fastapi.testclient import TestClient
from src.orchestrator.api import app

client = TestClient(app)

# Test 1: Submit request
response = client.post("/api/v1/request", json={
    "request": "Deploy Kuma",
    "user_id": "user123"
})
assert response.status_code == 200
result = response.json()
assert "request_id" in result
request_id = result["request_id"]
print("Test 1 passed: POST /api/v1/request works")

# Test 2: Get plan
response = client.get(f"/api/v1/plan/{request_id}")
assert response.status_code in [200, 404]  # 404 if plan not ready yet
print("Test 2 passed: GET /api/v1/plan/{request_id} works")

# Test 3: Approve plan (if plan exists)
if response.status_code == 200:
    plan = response.json()
    plan_id = plan["plan_id"]
    response = client.post(f"/api/v1/plan/{plan_id}/approve", json={
        "approved": True,
        "user_id": "user123"
    })
    assert response.status_code == 200
    print("Test 3 passed: POST /api/v1/plan/{plan_id}/approve works")

# Test 4: Get status
response = client.get(f"/api/v1/plan/{plan_id}/status")
assert response.status_code == 200
print("Test 4 passed: GET /api/v1/plan/{plan_id}/status works")
```

All endpoints should be accessible and return proper status codes.
  </verify>
  <done>
REST API endpoints created with submit_request, get_plan, approve_plan, get_plan_status, and request_status. All endpoints properly validate input, call OrchestratorService, and return structured responses with appropriate HTTP status codes.
  </done>
</task>

<task type="auto">
  <name>Task 3: Create E2E integration tests (tests/test_orchestrator_e2e.py)</name>
  <files>tests/test_orchestrator_e2e.py</files>
  <action>
Create tests/test_orchestrator_e2e.py with comprehensive E2E integration tests covering the full orchestrator workflow.

**Test Class 1: TestCompleteWorkflow** (async tests)
  - test_kuma_deployment_workflow: Full "Deploy Kuma and add portals" workflow:
    1. Submit request via submit_request()
    2. Generate plan via generate_plan()
    3. Verify plan structure (tasks, summary, complexity)
    4. Approve plan via approve_plan()
    5. Verify dispatch begins (status="executing")
    6. Verify tasks dispatched to agents
    7. Verify routing_decisions logged
  - test_simple_request_workflow: Simple single-task request ("Deploy Kuma"):
    1. Submit, generate, approve
    2. Verify quick execution
  - test_complex_request_workflow: Complex request with research ("Deploy Kuma, evaluate alternatives, and generate improvements")
    1. Submit, generate plan
    2. Verify complexity_level="complex"
    3. Verify will_use_external_ai=True
    4. Approve and execute

**Test Class 2: TestApprovalWorkflow**
  - test_plan_pending_approval_status: Generated plan has status="pending_approval"
  - test_user_can_approve: Approve changes status to "approved"
  - test_user_can_reject: Reject changes status to "rejected", stops execution
  - test_approval_timestamp_recorded: approved_at timestamp set on approval
  - test_cannot_approve_twice: Second approval attempt returns error or idempotent success

**Test Class 3: TestDispatch**
  - test_tasks_dispatched_to_correct_agents: Deploy task → infra agent, not code/research
  - test_routing_decisions_logged: Each task dispatch creates routing_decision record
  - test_dispatch_failure_retries: Agent fails first time, retried on different agent
  - test_all_dispatch_retries_fail: Final failure logged, task marked failed, plan continues
  - test_execution_order_maintained: Tasks execute in specified order

**Test Class 4: TestErrorHandling**
  - test_empty_request_rejected: Empty request string → 400 Bad Request
  - test_ambiguous_request_flagged: Vague request → requires_clarification status
  - test_out_of_scope_request_logged: Unknown agent request → out_of_scope list
  - test_plan_generation_failure_handled: If planner fails → error response, not exception
  - test_offline_agent_pool_detected: All infra agents offline → dispatch fails gracefully
  - test_fallback_triggered_on_complex: Complex plan automatically uses Claude

**Test Class 5: TestQuotaAndFallback**
  - test_low_quota_triggers_claude: Quota <20% → will_use_external_ai=True
  - test_complex_task_uses_claude: Complexity="complex" → will_use_external_ai=True
  - test_fallback_decision_logged: Fallback decision recorded in database
  - test_claude_failure_falls_back: Claude timeout → falls back to Ollama

**Test Class 6: TestAuditTrail**
  - test_request_logged_in_task_table: Task table records request_text, status
  - test_plan_logged: WorkPlan (or Task) records plan_id, complexity, will_use_external_ai
  - test_dispatch_logged_in_execution_logs: ExecutionLog entries for each dispatched task
  - test_routing_decisions_logged: routing_decisions table has entry per task dispatch
  - test_full_audit_trail_queryable: Can reconstruct full workflow from database

**Test Class 7: TestRESTAPI** (using FastAPI TestClient)
  - test_post_request_endpoint: POST /api/v1/request returns request_id
  - test_get_plan_endpoint: GET /api/v1/plan/{request_id} returns plan
  - test_post_approve_endpoint: POST /api/v1/plan/{plan_id}/approve starts execution
  - test_get_status_endpoint: GET /api/v1/plan/{plan_id}/status returns execution status
  - test_invalid_request_returns_400: Invalid input returns 400
  - test_not_found_returns_404: Nonexistent plan returns 404

**Test Fixtures**
  - orchestrator_service: OrchestratorService instance with all components (decomposer, planner, router, fallback)
  - mock_agent_pool: Pool with 2 infra agents (online, with deploy_service capability)
  - kuma_request: "Deploy Kuma Uptime and add existing portals to config"
  - simple_request: "Deploy Kuma"
  - complex_request: "Deploy Kuma, research alternatives, generate improvements"
  - db_session: Fresh database session with agent registry initialized
  - test_client: FastAPI TestClient for REST API testing

Use pytest fixtures, pytest.mark.asyncio, FastAPI TestClient.
Test coverage: >85% of orchestrator service and API endpoints.
  </action>
  <verify>
Run: `pytest tests/test_orchestrator_e2e.py -v --asyncio-mode=auto`

All tests pass (30+ test cases). Coverage report: `pytest tests/test_orchestrator_e2e.py --cov=src/orchestrator --cov-report=term-missing`

Verify:
  - test_kuma_deployment_workflow passes (full workflow)
  - test_simple_request_workflow passes
  - test_complex_request_workflow passes
  - test_plan_pending_approval_status passes
  - test_user_can_approve passes
  - test_tasks_dispatched_to_correct_agents passes
  - test_routing_decisions_logged passes
  - test_empty_request_rejected passes
  - test_offline_agent_pool_detected passes
  - test_post_request_endpoint passes (REST API)
  - All 30+ tests passing

Verify audit trail: `psql chiffon -c "SELECT * FROM tasks WHERE status='executing' LIMIT 5"` shows executing tasks.
  </verify>
  <done>
Comprehensive E2E test suite with 30+ test cases covering complete orchestrator workflow, approval process, dispatch, error handling, quota/fallback, audit trail, and REST API. All tests passing. Coverage >85%.
  </done>
</task>

</tasks>

<verification>
**Goal-backward check:**

1. ✓ User submits request → orchestrator parses (submit_request method)
2. ✓ Plan generated and presented (generate_plan method, REST API endpoint)
3. ✓ User approves plan (approve_plan method, REST API endpoint)
4. ✓ Work dispatched to agents (dispatch_plan method, uses router)
5. ✓ Full workflow end-to-end (E2E tests cover request → plan → approval → dispatch)

**Must-haves validation:**
- ✓ Request submission endpoint works
- ✓ Plan generation with human-readable summary
- ✓ Approval workflow changes status
- ✓ Agent routing via AgentRouter
- ✓ Execution logging to ExecutionLog
- ✓ Full audit trail in database

**Integration completeness:**
- ✓ RequestDecomposer integrated
- ✓ WorkPlanner integrated
- ✓ AgentRouter integrated
- ✓ ExternalAIFallback integrated
- ✓ RabbitMQ dispatch working
- ✓ PostgreSQL logging functional

**Success criteria (Phases 3 validation):**
- ✓ All 5 Phase 3 requirements addressed:
  - ORCH-01: Natural language to work plan (RequestDecomposer + WorkPlanner)
  - ORCH-02: Agent routing (AgentRouter)
  - ORCH-05: External AI fallback (ExternalAIFallback)
  - Additional: Human approval workflow (OrchestratorService)
  - Additional: Full E2E testing ("Deploy Kuma" workflow)
</verification>

<success_criteria>
- [ ] OrchestratorService extended with submit_request(), generate_plan(), approve_plan(), dispatch_plan(), get_plan_status()
- [ ] REST API endpoints created: POST /api/v1/request, GET /api/v1/plan/{request_id}, POST /api/v1/plan/{plan_id}/approve, GET /api/v1/plan/{plan_id}/status
- [ ] All endpoints use proper HTTP status codes (200, 400, 404, 409, 500)
- [ ] All endpoints have OpenAPI documentation
- [ ] Full request → plan → approval → dispatch workflow implemented and working
- [ ] All 30+ E2E tests passing
- [ ] Coverage >85% for orchestrator service and API
- [ ] Error handling for all failure scenarios
- [ ] Audit trail complete (Task, ExecutionLog, RoutingDecision, FallbackDecision tables)
- [ ] Complex request ("Deploy Kuma and add portals") workflow fully functional
- [ ] REST API tested with FastAPI TestClient
- [ ] All components (decomposer, planner, router, fallback) properly integrated
</success_criteria>

<output>
After completion, create `.planning/phases/03-orchestrator-core/03-05-SUMMARY.md` documenting:
- OrchestratorService methods and workflow
- REST API endpoints and status codes
- Complete "Deploy Kuma" workflow example
- Approval workflow state transitions
- Dispatch routing and execution logging
- Test results and coverage (30+ tests, >85% coverage)
- Integration points with Phase 4-8
- Post-Phase 3 verification checklist (all 5 success criteria met)
</output>
