# Phase 7 Plan 02: WebSocket Real-time Layer

---
phase: 07-user-interface
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - src/dashboard/websocket.py
  - src/dashboard/main.py
  - src/orchestrator/service.py
  - tests/test_dashboard_websocket.py
autonomous: true
must_haves:
  truths:
    - "WebSocket connection established between dashboard and client"
    - "Execution updates streamed in real-time to subscribed clients"
    - "Connection management handles disconnects gracefully"
    - "Fallback to polling available if WebSocket fails"
  artifacts:
    - path: "src/dashboard/websocket.py"
      provides: "WebSocket manager and handlers"
      exports: ["WebSocketManager", "ws_router"]
    - path: "tests/test_dashboard_websocket.py"
      provides: "WebSocket test coverage"
  key_links:
    - from: "src/dashboard/websocket.py"
      to: "src/orchestrator/service.py"
      via: "execution updates broadcast"
      pattern: "broadcast.*execution"
    - from: "src/dashboard/main.py"
      to: "src/dashboard/websocket.py"
      via: "router include"
      pattern: "include_router.*ws_router"
---

<objective>
Create WebSocket infrastructure for real-time execution updates. Clients subscribe to plan execution and receive step-by-step status updates, output streams, and completion notifications without polling.

Purpose: Real-time feedback is critical for user confidence during execution. Users need to see "Step 2 running..." not stale polling data. WebSocket provides sub-second updates.

Output: WebSocket manager with subscription model, message handlers, and graceful degradation to polling for unreliable connections.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@src/dashboard/api.py
@src/dashboard/models.py
@src/orchestrator/service.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create WebSocket manager</name>
  <files>
    src/dashboard/websocket.py
  </files>
  <action>
Create WebSocket connection manager for real-time updates:

1. Create src/dashboard/websocket.py

2. Import dependencies:
   - fastapi (WebSocket, WebSocketDisconnect, APIRouter)
   - asyncio
   - json
   - logging
   - datetime
   - typing (Dict, Set, Optional)

3. Create WebSocketManager class:

   class WebSocketManager:
       """Manages WebSocket connections and message broadcasting."""

       def __init__(self):
           # plan_id -> set of WebSocket connections
           self._plan_subscriptions: Dict[str, Set[WebSocket]] = {}
           # session_id -> WebSocket connection
           self._session_connections: Dict[str, WebSocket] = {}
           # WebSocket -> metadata (session_id, subscribed_plans, connected_at)
           self._connection_metadata: Dict[WebSocket, dict] = {}
           self.logger = logging.getLogger("dashboard.websocket")

       async def connect(self, websocket: WebSocket, session_id: str) -> None:
           """Accept WebSocket connection and register session."""
           await websocket.accept()
           self._session_connections[session_id] = websocket
           self._connection_metadata[websocket] = {
               "session_id": session_id,
               "subscribed_plans": set(),
               "connected_at": datetime.utcnow(),
           }
           self.logger.info(f"WebSocket connected: session={session_id}")

       async def disconnect(self, websocket: WebSocket) -> None:
           """Clean up on disconnect."""
           metadata = self._connection_metadata.get(websocket, {})
           session_id = metadata.get("session_id")

           # Remove from plan subscriptions
           for plan_id in metadata.get("subscribed_plans", set()):
               if plan_id in self._plan_subscriptions:
                   self._plan_subscriptions[plan_id].discard(websocket)

           # Remove session connection
           if session_id and session_id in self._session_connections:
               del self._session_connections[session_id]

           # Remove metadata
           if websocket in self._connection_metadata:
               del self._connection_metadata[websocket]

           self.logger.info(f"WebSocket disconnected: session={session_id}")

       async def subscribe_to_plan(self, websocket: WebSocket, plan_id: str) -> None:
           """Subscribe connection to plan execution updates."""
           if plan_id not in self._plan_subscriptions:
               self._plan_subscriptions[plan_id] = set()
           self._plan_subscriptions[plan_id].add(websocket)

           # Track in metadata
           if websocket in self._connection_metadata:
               self._connection_metadata[websocket]["subscribed_plans"].add(plan_id)

           self.logger.info(f"Subscribed to plan: {plan_id}")

       async def unsubscribe_from_plan(self, websocket: WebSocket, plan_id: str) -> None:
           """Unsubscribe from plan updates."""
           if plan_id in self._plan_subscriptions:
               self._plan_subscriptions[plan_id].discard(websocket)

           if websocket in self._connection_metadata:
               self._connection_metadata[websocket]["subscribed_plans"].discard(plan_id)

       async def broadcast_to_plan(self, plan_id: str, message: dict) -> None:
           """Broadcast message to all subscribers of a plan."""
           if plan_id not in self._plan_subscriptions:
               return

           # Add timestamp and plan_id to message
           message["plan_id"] = plan_id
           message["timestamp"] = datetime.utcnow().isoformat()

           dead_connections = []
           for websocket in self._plan_subscriptions[plan_id]:
               try:
                   await websocket.send_json(message)
               except Exception as e:
                   self.logger.warning(f"Failed to send to websocket: {e}")
                   dead_connections.append(websocket)

           # Clean up dead connections
           for ws in dead_connections:
               await self.disconnect(ws)

       async def send_to_session(self, session_id: str, message: dict) -> bool:
           """Send message to specific session."""
           websocket = self._session_connections.get(session_id)
           if not websocket:
               return False

           try:
               message["timestamp"] = datetime.utcnow().isoformat()
               await websocket.send_json(message)
               return True
           except Exception as e:
               self.logger.warning(f"Failed to send to session {session_id}: {e}")
               return False

       def get_plan_subscriber_count(self, plan_id: str) -> int:
           """Get number of subscribers for a plan."""
           return len(self._plan_subscriptions.get(plan_id, set()))

       def get_connection_count(self) -> int:
           """Get total active connection count."""
           return len(self._connection_metadata)

4. Create global manager instance:
   ws_manager = WebSocketManager()
  </action>
  <verify>
    - [ ] WebSocketManager tracks connections by session
    - [ ] Plan subscriptions work (subscribe, unsubscribe, broadcast)
    - [ ] Dead connections cleaned up automatically
    - [ ] Import works: `from src.dashboard.websocket import ws_manager`
  </verify>
  <done>WebSocket manager created with subscription and broadcast support</done>
</task>

<task type="auto">
  <name>Task 2: Create WebSocket endpoint and message handlers</name>
  <files>
    src/dashboard/websocket.py
    src/dashboard/main.py
  </files>
  <action>
Add WebSocket endpoint and message protocol:

1. Add to src/dashboard/websocket.py:

   Create ws_router = APIRouter()

   Define message types (enum or constants):
   - CLIENT_SUBSCRIBE = "subscribe"
   - CLIENT_UNSUBSCRIBE = "unsubscribe"
   - CLIENT_PING = "ping"
   - SERVER_EXECUTION_UPDATE = "execution_update"
   - SERVER_STEP_STATUS = "step_status"
   - SERVER_STEP_OUTPUT = "step_output"
   - SERVER_PLAN_COMPLETED = "plan_completed"
   - SERVER_PLAN_FAILED = "plan_failed"
   - SERVER_PONG = "pong"
   - SERVER_ERROR = "error"

   @ws_router.websocket("/ws/{session_id}")
   async def websocket_endpoint(websocket: WebSocket, session_id: str):
       """WebSocket endpoint for real-time updates."""
       await ws_manager.connect(websocket, session_id)

       try:
           while True:
               # Receive message with timeout for keepalive
               data = await asyncio.wait_for(
                   websocket.receive_json(),
                   timeout=60.0  # 60 second timeout
               )

               await handle_client_message(websocket, session_id, data)

       except WebSocketDisconnect:
           await ws_manager.disconnect(websocket)
       except asyncio.TimeoutError:
           # Send ping to check connection
           try:
               await websocket.send_json({"type": "ping"})
           except:
               await ws_manager.disconnect(websocket)
       except Exception as e:
           logger.error(f"WebSocket error: {e}")
           await ws_manager.disconnect(websocket)

   async def handle_client_message(websocket: WebSocket, session_id: str, data: dict):
       """Handle incoming client messages."""
       msg_type = data.get("type")

       if msg_type == "subscribe":
           plan_id = data.get("plan_id")
           if plan_id:
               await ws_manager.subscribe_to_plan(websocket, plan_id)
               await websocket.send_json({
                   "type": "subscribed",
                   "plan_id": plan_id
               })

       elif msg_type == "unsubscribe":
           plan_id = data.get("plan_id")
           if plan_id:
               await ws_manager.unsubscribe_from_plan(websocket, plan_id)
               await websocket.send_json({
                   "type": "unsubscribed",
                   "plan_id": plan_id
               })

       elif msg_type == "ping":
           await websocket.send_json({"type": "pong"})

       else:
           await websocket.send_json({
               "type": "error",
               "message": f"Unknown message type: {msg_type}"
           })

2. Add helper functions for broadcasting execution updates:

   async def broadcast_step_update(
       plan_id: str,
       step_index: int,
       step_name: str,
       status: str,
       output: Optional[str] = None,
       error: Optional[str] = None
   ):
       """Broadcast step status change to all plan subscribers."""
       await ws_manager.broadcast_to_plan(plan_id, {
           "type": "step_status",
           "step_index": step_index,
           "step_name": step_name,
           "status": status,
           "output": output,
           "error": error,
       })

   async def broadcast_step_output(
       plan_id: str,
       step_index: int,
       output_chunk: str
   ):
       """Broadcast step output chunk (for streaming logs)."""
       await ws_manager.broadcast_to_plan(plan_id, {
           "type": "step_output",
           "step_index": step_index,
           "output": output_chunk,
       })

   async def broadcast_plan_completed(plan_id: str, summary: dict):
       """Broadcast plan completion."""
       await ws_manager.broadcast_to_plan(plan_id, {
           "type": "plan_completed",
           "summary": summary,
       })

   async def broadcast_plan_failed(plan_id: str, error: str):
       """Broadcast plan failure."""
       await ws_manager.broadcast_to_plan(plan_id, {
           "type": "plan_failed",
           "error": error,
       })

3. Update src/dashboard/main.py:
   - Import ws_router from websocket
   - Include ws_router: app.include_router(ws_router)
   - Make ws_manager available globally for orchestrator callbacks
  </action>
  <verify>
    - [ ] WebSocket endpoint accepts connections at /ws/{session_id}
    - [ ] Subscribe/unsubscribe messages work
    - [ ] Ping/pong keepalive works
    - [ ] Broadcast helpers available for orchestrator integration
  </verify>
  <done>WebSocket endpoint and message handlers created with full protocol support</done>
</task>

<task type="auto">
  <name>Task 3: Create WebSocket tests and fallback polling</name>
  <files>
    src/dashboard/api.py
    tests/test_dashboard_websocket.py
  </files>
  <action>
Add fallback polling endpoint and comprehensive WebSocket tests:

1. Add polling fallback to src/dashboard/api.py:

   GET /api/dashboard/plan/{plan_id}/poll
   - For clients that cannot maintain WebSocket
   - Returns current execution state
   - Includes X-Poll-Interval header (recommend 2 seconds)
   - Body: {steps: list[StepStatus], overall_status: str, last_update: datetime}

2. Create tests/test_dashboard_websocket.py:

   TestWebSocketManager:
   - test_connect_registers_session: Connection stored with session_id
   - test_disconnect_cleans_up: All references removed
   - test_subscribe_to_plan: Subscription tracked correctly
   - test_unsubscribe_from_plan: Subscription removed
   - test_broadcast_to_plan_sends_to_subscribers: All subscribers receive
   - test_broadcast_skips_dead_connections: Dead connections cleaned up
   - test_send_to_session: Direct message to session works
   - test_get_subscriber_count: Correct count returned

   TestWebSocketEndpoint:
   - test_connect_accept: Connection accepted with valid session
   - test_subscribe_message: Subscribe message adds subscription
   - test_unsubscribe_message: Unsubscribe removes subscription
   - test_ping_pong: Ping returns pong
   - test_unknown_message_returns_error: Invalid type returns error
   - test_disconnect_cleanup: Resources freed on disconnect

   TestBroadcastHelpers:
   - test_broadcast_step_update: Correct message format
   - test_broadcast_step_output: Output chunks sent
   - test_broadcast_plan_completed: Completion message correct
   - test_broadcast_plan_failed: Failure message includes error

   TestPollingFallback:
   - test_poll_returns_current_state: GET returns execution state
   - test_poll_includes_interval_header: X-Poll-Interval present
   - test_poll_without_websocket: Works independently of WS

3. Use pytest-asyncio and FastAPI TestClient with websocket_connect

4. Test fixtures:
   - mock_websocket: Mock WebSocket for unit tests
   - ws_test_client: TestClient with WebSocket support
   - test_manager: Fresh WebSocketManager instance
  </action>
  <verify>
    - [ ] All WebSocket tests pass: `pytest tests/test_dashboard_websocket.py -v`
    - [ ] Polling fallback returns correct state
    - [ ] Connection lifecycle tested (connect, subscribe, disconnect)
    - [ ] Broadcast to multiple subscribers tested
  </verify>
  <done>WebSocket tests and polling fallback created</done>
</task>

</tasks>

<verification>
After all tasks complete:
1. Start dashboard: `uvicorn src.dashboard.main:app --port 8001`
2. Test WebSocket: `websocat ws://localhost:8001/ws/test-session` (send {"type": "ping"})
3. Test polling: `curl http://localhost:8001/api/dashboard/plan/test-plan/poll`
4. Run tests: `pytest tests/test_dashboard_websocket.py -v`
</verification>

<success_criteria>
- WebSocket endpoint accepts connections at /ws/{session_id}
- Subscription model works (subscribe to plan, receive updates)
- Broadcast to all subscribers works reliably
- Dead connections cleaned up automatically
- Ping/pong keepalive prevents timeouts
- Polling fallback available for unreliable connections
- All tests pass (target: 20+ test cases)
</success_criteria>

<output>
After completion, create `.planning/phases/07-user-interface/07-02-SUMMARY.md`
</output>
