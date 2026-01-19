# Phase 2: Message Bus & Agent Communication - Context

**Gathered:** 2026-01-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Deploy RabbitMQ as the message bus for agent communication. Implement the agent communication protocol with work dispatch and status updates. Provide REST API for orchestrator operations. All agents can send/receive messages, and the orchestrator can query agent status and resources.

</domain>

<decisions>
## Implementation Decisions

### Queue Topology & Routing

- **Work dispatch:** Single work queue. All agents listen. Agent type specified in message header for filtering.
- **Status updates:** Single reply queue. Agents publish status updates; orchestrator correlates by correlation ID.
- **System announcements:** Separate broadcast queue for system-wide announcements (pause/resume, maintenance, quota alerts).
- **Work priority:** 5 priority levels: critical, high, normal, low, background. Agents check priority queues in order.
- **Message acknowledgment:** Agents must ack after work starts. If agent crashes, message requeues for another agent.
- **Failed messages:** After N retries, log and discard. No infinite retry loops; orchestrator checks logs for failures.
- **Work ordering:** No strict FIFO. Any order allowed as long as dependencies are respected.
- **Agent discovery:** Active registration on startup + periodic heartbeats (60s interval). Orchestrator maintains agent registry.

### Message Persistence & Durability

- **Disk persistence:** Configurable per message. Priority: critical/high messages persist to disk; normal/low stay in memory for speed.
- **History retention:** Keep messages in RabbitMQ for 7 days. Archive older messages to PostgreSQL for long-term audit trail.
- **Orchestrator restart:** Pause/resume in-flight work (requires idempotent agents). Do not restart from scratch.
- **State recovery:** On orchestrator restart, query agents for current status instead of relying on DB. Trust agent reports.

### REST API Surface & Security

- **Endpoints:**
  - `POST /api/v1/dispatch` — Submit new work request
  - `GET /api/v1/status/{task_id}` — Query task status and progress
  - `GET /api/v1/agents` — List connected agents with resource status
  - `POST /api/v1/cancel/{task_id}` — Cancel running task

- **Authentication:** API key in header (Bearer token pattern). Simple for v1.
- **Rate limiting:** None for v1. Single developer; add later if needed.
- **Versioning:** All endpoints use `/api/v1/` prefix for forward compatibility.
- **Agent filtering:** GET /api/v1/agents supports query parameters (`?agent_type=infra&status=online`).
- **Real-time updates:** WebSocket support for live task status updates. Alternative to polling.

### Agent Reconnection & Heartbeat

- **Heartbeat interval:** Every 60 seconds. Agents send alive signal to orchestrator.
- **Offline threshold:** 3 missed heartbeats (180 seconds) before marking agent offline.
- **Heartbeat content:** Agent ID + type, available resource metrics (CPU, GPU VRAM), current task ID being worked on.
- **Reconnection behavior:** Claude's discretion. Determine whether to resume or requeue based on idempotency analysis.

### Claude's Discretion

- **Work recovery on agent reconnect** — Decide whether pause/resume or requeue based on agent capability
- **Exact retry count before discard** — Set appropriate N for failed message retry limit
- **REST API error response format** — Use standard HTTP + JSON conventions
- **Message routing optimization** — Optimize queue topology based on performance testing

</decisions>

<specifics>
## Specific Ideas

- Queue topology inspired by RabbitMQ patterns (work queues + pub/sub for broadcast)
- Correlation ID pattern matches standard async task systems (Celery, Luigi)
- Heartbeat + registration ensures robust agent lifecycle management
- WebSocket for real-time UI feedback (for Phase 7)
- Priority queues support GPU-heavy, time-sensitive, and background work differentiation

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (Phase 3 will handle orchestrator planning logic; Phase 4 will use these metrics for resource-aware scheduling.)

</deferred>

---

*Phase: 02-message-bus*
*Context gathered: 2026-01-19*
