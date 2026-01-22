# Phase 7 Plan 01: Dashboard Backend API

---
phase: 07-user-interface
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/dashboard/__init__.py
  - src/dashboard/api.py
  - src/dashboard/models.py
  - src/dashboard/main.py
  - tests/test_dashboard_api.py
autonomous: true
must_haves:
  truths:
    - "Dashboard API serves as single entry point for web UI"
    - "All endpoints proxy to orchestrator API (no duplicate logic)"
    - "Chat history persisted for session continuity"
    - "Plan modification requests supported via chat interface"
  artifacts:
    - path: "src/dashboard/__init__.py"
      provides: "Dashboard module exports"
      exports: ["dashboard_router", "ChatSession", "ChatMessage"]
    - path: "src/dashboard/api.py"
      provides: "Dashboard REST API endpoints"
      exports: ["router"]
    - path: "src/dashboard/models.py"
      provides: "Dashboard-specific Pydantic models"
      exports: ["ChatSession", "ChatMessage", "DashboardPlanView"]
  key_links:
    - from: "src/dashboard/api.py"
      to: "src/orchestrator/api.py"
      via: "HTTP client proxy"
      pattern: "httpx\\.AsyncClient.*orchestrator"
    - from: "src/dashboard/main.py"
      to: "src/dashboard/api.py"
      via: "FastAPI router include"
      pattern: "app\\.include_router"
---

<objective>
Create the dashboard backend API layer that serves as the entry point for the web UI. This API proxies requests to the orchestrator and adds dashboard-specific functionality like chat sessions and message history.

Purpose: The dashboard backend provides a clean separation between the UI and orchestrator, enabling session management, chat history, and UI-specific formatting without polluting the core orchestrator API.

Output: Working FastAPI application with endpoints for chat, plan review, and execution monitoring that integrate with the existing orchestrator.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@src/orchestrator/api.py
@src/orchestrator/service.py
@src/common/models.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create dashboard models and session management</name>
  <files>
    src/dashboard/__init__.py
    src/dashboard/models.py
  </files>
  <action>
Create dashboard-specific models for chat sessions and UI state:

1. Create src/dashboard/__init__.py:
   ```python
   """Dashboard API for Chiffon web interface.

   Provides:
   - Chat session management
   - Plan review and approval workflows
   - Real-time execution updates
   """
   from .api import router as dashboard_router
   from .models import ChatSession, ChatMessage, DashboardPlanView

   __all__ = ["dashboard_router", "ChatSession", "ChatMessage", "DashboardPlanView"]
   ```

2. Create src/dashboard/models.py with Pydantic models:

   ChatMessage:
   - id: str (UUID)
   - session_id: str (UUID)
   - role: Literal["user", "assistant", "system"]
   - content: str
   - timestamp: datetime
   - metadata: Optional[dict] (for plan_id, request_id references)

   ChatSession:
   - session_id: str (UUID)
   - user_id: str
   - created_at: datetime
   - last_activity: datetime
   - messages: list[ChatMessage]
   - current_request_id: Optional[str]
   - current_plan_id: Optional[str]
   - status: Literal["idle", "awaiting_plan", "plan_ready", "executing", "completed"]

   DashboardPlanView:
   - plan_id: str
   - request_id: str
   - summary: str (human-readable)
   - steps: list[dict] (step-by-step breakdown with checkboxes)
   - estimated_duration: str (human-readable like "~5 minutes")
   - risk_level: Literal["low", "medium", "high"]
   - resource_requirements: dict
   - status: str
   - can_approve: bool
   - can_modify: bool
   - can_abort: bool

   ModificationRequest:
   - plan_id: str
   - user_message: str (natural language modification request)
   - session_id: str

   ExecutionUpdate:
   - plan_id: str
   - step_index: int
   - step_name: str
   - status: Literal["pending", "running", "completed", "failed", "skipped"]
   - output: Optional[str]
   - error: Optional[str]
   - started_at: Optional[datetime]
   - completed_at: Optional[datetime]

3. Add session storage class (in-memory for v1, easy to swap for Redis later):

   SessionStore:
   - _sessions: dict[str, ChatSession]
   - create_session(user_id: str) -> ChatSession
   - get_session(session_id: str) -> Optional[ChatSession]
   - add_message(session_id: str, message: ChatMessage) -> None
   - update_session_status(session_id: str, status: str) -> None
   - cleanup_expired(max_age_hours: int = 24) -> int
  </action>
  <verify>
    - [ ] ChatMessage and ChatSession models validate correctly
    - [ ] DashboardPlanView formats plan data for UI consumption
    - [ ] SessionStore manages session lifecycle
    - [ ] Python imports work: `from src.dashboard.models import ChatSession, ChatMessage`
  </verify>
  <done>Dashboard models created with session management support</done>
</task>

<task type="auto">
  <name>Task 2: Create dashboard REST API endpoints</name>
  <files>
    src/dashboard/api.py
  </files>
  <action>
Create FastAPI router with dashboard endpoints that proxy to orchestrator:

1. Create src/dashboard/api.py

2. Import dependencies:
   - FastAPI (APIRouter, HTTPException, Depends, Query)
   - httpx for async HTTP client
   - Dashboard models (ChatSession, ChatMessage, DashboardPlanView, etc.)
   - Logging

3. Create router with prefix "/api/dashboard"

4. Endpoints:

   POST /api/dashboard/session
   - Create new chat session
   - Body: {user_id: str}
   - Returns: ChatSession

   GET /api/dashboard/session/{session_id}
   - Get session with message history
   - Returns: ChatSession with messages

   POST /api/dashboard/chat
   - Submit chat message (deployment request or modification)
   - Body: {session_id: str, message: str}
   - Logic:
     a. Add user message to session
     b. If message looks like deployment request (no current plan):
        - Call orchestrator POST /api/v1/request
        - Store request_id in session
        - Call orchestrator GET /api/v1/plan/{request_id}
        - Store plan_id in session
        - Return plan summary as assistant message
     c. If message is modification request (has current plan):
        - Pass to orchestrator with modification context
        - Update plan_id if new plan generated
        - Return updated plan summary
   - Returns: {messages: [new_messages], plan: Optional[DashboardPlanView]}

   GET /api/dashboard/plan/{plan_id}
   - Get plan in dashboard-friendly format
   - Proxy to orchestrator GET /api/v1/plan/{request_id}/status
   - Transform to DashboardPlanView with:
     - Human-readable summary
     - Step checklist format
     - Risk level assessment
   - Returns: DashboardPlanView

   POST /api/dashboard/plan/{plan_id}/approve
   - Approve plan for execution
   - Proxy to orchestrator POST /api/v1/plan/{plan_id}/approve
   - Update session status to "executing"
   - Returns: {status: "approved", execution_started: bool}

   POST /api/dashboard/plan/{plan_id}/reject
   - Reject plan
   - Proxy to orchestrator POST /api/v1/plan/{plan_id}/approve with approved=false
   - Update session status to "idle"
   - Add rejection message to chat
   - Returns: {status: "rejected"}

   POST /api/dashboard/plan/{plan_id}/modify
   - Request plan modification via chat
   - Body: ModificationRequest
   - Re-submit to orchestrator with modification context
   - Returns: {new_plan: DashboardPlanView}

   GET /api/dashboard/plan/{plan_id}/status
   - Get execution status for polling
   - Proxy to orchestrator
   - Returns: {status: str, steps: list[ExecutionUpdate]}

   POST /api/dashboard/plan/{plan_id}/abort
   - Abort running execution
   - Call orchestrator cancel endpoint for each task
   - Returns: {status: "aborted"}

5. Add internal helper:
   - _format_plan_for_dashboard(orchestrator_plan: dict) -> DashboardPlanView
     Transforms orchestrator plan into UI-friendly format with:
     - Duration estimates in human readable form
     - Risk level derived from complexity
     - Step checklist markdown format

6. Use httpx.AsyncClient for orchestrator API calls:
   - Base URL from config (ORCHESTRATOR_URL, default http://localhost:8000)
   - Timeout of 30 seconds
   - Retry logic with max 3 attempts
  </action>
  <verify>
    - [ ] All endpoints return correct response schemas
    - [ ] Session management works (create, get, update)
    - [ ] Chat endpoint handles both new requests and modifications
    - [ ] Plan approval/rejection proxies correctly
    - [ ] Abort endpoint cancels running tasks
  </verify>
  <done>Dashboard REST API created with full chat and approval workflow endpoints</done>
</task>

<task type="auto">
  <name>Task 3: Create dashboard FastAPI application and tests</name>
  <files>
    src/dashboard/main.py
    tests/test_dashboard_api.py
  </files>
  <action>
Create the main application entry point and comprehensive tests:

1. Create src/dashboard/main.py:
   - Create FastAPI app with title "Chiffon Dashboard"
   - Include dashboard router
   - Add CORS middleware (allow localhost origins for dev)
   - Add health check endpoint GET /health
   - Add lifespan for session cleanup task
   - Configure logging

2. Create tests/test_dashboard_api.py:

   TestChatSessionManagement:
   - test_create_session: POST /api/dashboard/session returns session with ID
   - test_get_session: GET returns session with messages
   - test_session_not_found: GET with invalid ID returns 404
   - test_session_stores_messages: Messages persist in session

   TestChatEndpoint:
   - test_new_deployment_request: Chat triggers orchestrator request + plan
   - test_modification_request: Chat with active plan triggers modification
   - test_empty_message_rejected: Empty message returns 400
   - test_session_required: Missing session_id returns 400

   TestPlanEndpoints:
   - test_get_plan_formats_for_ui: Plan includes human-readable summary
   - test_plan_approval_proxies: Approval calls orchestrator
   - test_plan_rejection_proxies: Rejection calls orchestrator
   - test_plan_modification_returns_new_plan: Modify returns updated plan
   - test_plan_not_found: Invalid plan_id returns 404

   TestExecutionStatus:
   - test_status_polling: GET status returns step updates
   - test_abort_cancels_tasks: Abort calls cancel on orchestrator

   TestDashboardPlanView:
   - test_risk_level_from_complexity: simple->low, medium->medium, complex->high
   - test_duration_human_readable: 300 seconds -> "~5 minutes"
   - test_step_checklist_format: Steps have checkbox format

3. Use pytest fixtures:
   - mock_orchestrator: Mock httpx responses
   - test_session: Pre-created session
   - sample_plan: Sample orchestrator plan response

4. Use pytest-asyncio for async tests

5. Use respx for mocking httpx calls to orchestrator
  </action>
  <verify>
    - [ ] Dashboard app starts: `uvicorn src.dashboard.main:app --port 8001`
    - [ ] Health check returns 200
    - [ ] All tests pass: `pytest tests/test_dashboard_api.py -v`
    - [ ] Tests mock orchestrator calls (no real orchestrator needed)
  </verify>
  <done>Dashboard FastAPI app created with comprehensive test suite</done>
</task>

</tasks>

<verification>
After all tasks complete:
1. Start dashboard: `uvicorn src.dashboard.main:app --port 8001`
2. Test health: `curl http://localhost:8001/health`
3. Run tests: `pytest tests/test_dashboard_api.py -v`
4. Verify imports: `python -c "from src.dashboard import dashboard_router, ChatSession"`
</verification>

<success_criteria>
- Dashboard API runs independently on port 8001
- Chat session management works (create, get, messages)
- Chat endpoint handles deployment requests and modifications
- Plan endpoints (get, approve, reject, modify, status, abort) all functional
- Plans formatted for UI consumption (human-readable, checklist format)
- All tests pass (target: 25+ test cases)
- No orchestrator logic duplicated (all proxied via HTTP)
</success_criteria>

<output>
After completion, create `.planning/phases/07-user-interface/07-01-SUMMARY.md`
</output>
