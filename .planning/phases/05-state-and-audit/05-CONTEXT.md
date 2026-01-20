# Phase 5: State & Audit Integration - Context

**Gathered:** 2026-01-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Execution results tracked in PostgreSQL with rich audit data. All decisions and outcomes recorded for real-time queries and post-mortem analysis. Audit trail supports filtering by time, service, status, and inferred intent. State recovery after orchestrator restart. Resource constraint management via pause/resume mechanism.

**Out of scope:** Git commits for audit trail (PostgreSQL only); multi-orchestrator state synchronization; suggestion generation (scaffolding for v2).

</domain>

<decisions>
## Implementation Decisions

### Audit Storage Strategy
- **PostgreSQL only** — No git commits for audit trail; PostgreSQL is source of truth for execution logs
- Append-only tasks table (INSERT only, never UPDATE/DELETE on core fields)
- Triggers prevent modification of task records (immutability enforcement)
- Single tasks table with JSON outcome field: `task_id, status, outcome (JSON), resources_used (JSON), services_touched (array), created_at, updated_at`

### Audit Data Capture
- **Plan details captured:** Steps executed, estimated vs. actual duration, complexity assessment
- **Service tagging:** Array of services touched (supports multi-service tasks, e.g., DNS + auth)
- **Resource tracking detailed:** CPU time, wall-clock duration, GPU VRAM used, peak memory, agent load % at execution time
- **Outcome format:** Summarized output (success/error, key messages, last N lines of ansible output)

### Query Interface & Optimization
- **REST API endpoints** for audit queries (`/api/v1/audit/failures`, `/api/v1/audit/by-service`, etc.)
- **Query support:** Combined filtering (status + time range + service + inferred intent)
- **Intent queries:** Infer from service + action type during query (not stored as separate field)
- **Indexes:** Composite (status, created_at) + GIN on services array for efficient filtering

### Pause/Resume Mechanism
- **Trigger:** Pause BEFORE dispatch if insufficient capacity on available agents
- **State persistence:** Paused work stored in pause_queue table (survives orchestrator restart)
- **Control mode:** Hybrid automatic/manual — auto-resume when capacity available, but user can manually pause/override
- **Restart recovery:** Both pause_queue replay + in-progress task recovery (check agent status, resume or retry)

### Post-Mortem Scaffolding
- **Failure capture:** Error message + stack trace, resource state at failure, task context (plan, agent, step)
- **Suggestions storage:** JSON array field on tasks table (suggestions field)
- **Suggestion generation:** Scaffolding only in v1 (field exists, unpopulated); v2 post-mortem agent populates after execution
- **Future extensibility:** Schema supports future annotation of applied suggestions

### Claude's Discretion
- Query optimization implementation details (SQL patterns, caching strategy)
- Exact pause threshold percentage (e.g., pause if all agents <20% capacity)
- Error recovery retry logic (max retries, backoff strategy)
- Pause queue ordering (FIFO vs. priority-based)

</decisions>

<specifics>
## Specific Ideas

- Intent search capability valuable for filtering by task type (deploy_kuma, add_portals, etc.); infer from service + action during queries
- Audit trail should be queryable from UI for transparency: "show me all Kuma changes in the past week"
- Failure analysis should be easy: "which tasks failed due to resource constraints vs. application errors"

</specifics>

<deferred>
## Deferred Ideas

- Git audit commits — Evaluated but deferred; PostgreSQL provides sufficient audit trail for v1. Revisit if immutable git ledger required for compliance in v2.
- Multi-orchestrator state synchronization — Covered in Phase 5+ planning; assumes single orchestrator for v1
- Suggestion generation in v1 — Deferred to v2 post-mortem agent; v1 provides scaffolding only
- Explicit suggestion tracking (applied vs. rejected) — Future enhancement; v1 stores suggestions as reference only

</deferred>

---

*Phase: 05-state-and-audit*
*Context gathered: 2026-01-20*
