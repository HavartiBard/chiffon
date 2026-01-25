---
phase: 03-orchestrator-core
plan: 03
type: execute
wave: 1
depends_on: ["03-01", "03-02"]
files_modified:
  - src/orchestrator/router.py
  - src/common/models.py
  - alembic/versions/[new_migration]_agent_registry.py
  - tests/test_agent_router.py
autonomous: true
must_haves:
  truths:
    - "Agent registry stores capabilities, specializations, and online status"
    - "Agent performance tracking records success rates and execution history"
    - "Routing algorithm scores agents by success rate, recent context, specialization"
    - "Router selects best available agent from pool based on weighted scoring"
    - "Routing decisions logged to database for full audit trail"
  artifacts:
    - path: "src/orchestrator/router.py"
      provides: "AgentRouter class with route_task() and dispatch_with_retry()"
      exports: ["AgentRouter", "AgentSelection"]
    - path: "src/common/models.py"
      provides: "AgentRegistry and AgentPerformance SQLAlchemy models"
      contains: "class AgentRegistry, class AgentPerformance, class RoutingDecision"
    - path: "alembic/versions/[timestamp]_agent_registry.py"
      provides: "Migration creating agent_registry, agent_performance, routing_decisions tables"
      contains: "CREATE TABLE agent_registry"
  key_links:
    - from: "AgentRouter"
      to: "AgentRegistry"
      via: "queries db for agents with capability and online status"
      pattern: "db.query.*agent_registry.*online"
    - from: "AgentRouter"
      to: "AgentPerformance"
      via: "calculates success rates from performance table"
      pattern: "agent_performance.*success_count.*failure_count"
    - from: "route_task"
      to: "WorkTask"
      via: "takes WorkTask as input, returns AgentSelection"
      pattern: "route_task.*WorkTask.*AgentSelection"
---

<objective>
Build the agent routing and capability matching layer that selects the best available agent for each task based on performance, specialization, and resource availability.

Purpose: Enable intelligent task-to-agent matching using pool-based assignment with performance-driven routing. Track agent capabilities, success rates, and specializations; route work to agents most likely to succeed while maintaining full audit trail.

Output: AgentRouter service with agent registry, performance tracking, and comprehensive routing tests validating agent selection, scoring, retry logic, and audit logging.
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
@src/common/models.py
@src/common/database.py
@alembic/versions
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add agent registry and performance tracking models to src/common/models.py</name>
  <files>src/common/models.py</files>
  <action>
Add three SQLAlchemy ORM models to src/common/models.py (after ExecutionLog, before Pydantic models):

1. **AgentRegistry** - Tracks agent capabilities and status:
   - agent_id: UUID, primary_key=True
   - agent_type: String(50), NOT NULL (infra|code|research|desktop)
   - pool_name: String(100), NOT NULL (e.g., "infra_pool_1")
   - capabilities: JSON, NOT NULL (list of work types this agent can do)
   - specializations: JSON, nullable (e.g., ["config_specialist", "deployment_expert"])
   - status: String(50), default="offline" (online|offline|busy)
   - last_heartbeat_at: DateTime, nullable
   - created_at: DateTime, default=now()
   - updated_at: DateTime, default=now()
   - indexes on (agent_type, status) and (pool_name) for fast queries

2. **AgentPerformance** - Tracks success rates and execution history:
   - id: Integer, primary_key=True
   - agent_id: UUID, FK to agent_registry, NOT NULL
   - work_type: String(100), NOT NULL (e.g., "deploy_service")
   - success_count: Integer, default=0
   - failure_count: Integer, default=0
   - total_duration_ms: Integer, default=0 (sum of all execution times)
   - last_execution_at: DateTime, nullable
   - difficulty_assessment: String(50), nullable (straightforward|tricky|failed)
   - created_at: DateTime, default=now()
   - updated_at: DateTime, default=now()
   - UNIQUE constraint on (agent_id, work_type)

3. **RoutingDecision** - Audit trail for all routing decisions:
   - id: Integer, primary_key=True
   - task_id: UUID, nullable
   - work_type: String(100), NOT NULL
   - agent_pool: String(100), NOT NULL
   - selected_agent_id: UUID, FK to agent_registry
   - success_rate_percent: Integer (0-100)
   - specialization_match: Boolean, default=False
   - recent_context_match: Boolean, default=False
   - retried: Boolean, default=False
   - reason: String (explanation of selection)
   - created_at: DateTime, default=now()
   - indexes on (task_id, work_type, created_at) for audit queries

Use SQLAlchemy declarative syntax (Base.metadata), add helpful docstrings, configure relationships.
  </action>
  <verify>
Test import: `python -c "from src.common.models import AgentRegistry, AgentPerformance, RoutingDecision; print('Models imported')"`.

Verify models can be instantiated and have correct table names:
```python
from src.common.models import AgentRegistry, AgentPerformance
from uuid import uuid4

agent = AgentRegistry(agent_id=uuid4(), agent_type="infra", pool_name="pool_1", capabilities=["deploy_service"])
perf = AgentPerformance(agent_id=agent.agent_id, work_type="deploy_service", success_count=5, failure_count=1)

assert agent.__tablename__ == "agent_registry"
assert perf.__tablename__ == "agent_performance"
print("Models valid")
```
  </verify>
  <done>
AgentRegistry, AgentPerformance, and RoutingDecision models added to models.py with proper SQLAlchemy configuration. Models map to correct tables with appropriate indexes and constraints.
  </done>
</task>

<task type="auto">
  <name>Task 2: Create Alembic migration for agent registry tables</name>
  <files>alembic/versions/[timestamp]_agent_registry.py</files>
  <action>
Create a new Alembic migration file (auto-generated via `alembic revision --autogenerate -m "Add agent registry and performance tracking"`) that creates the three new tables:

Migration file should:
1. Import sqlalchemy.op and sqlalchemy function
2. revision and down_revision globals set correctly
3. Create agent_registry table with all columns and indexes
4. Create agent_performance table with all columns, unique constraint, and FK
5. Create routing_decisions table with all columns and indexes
6. Implement upgrade() function that creates all tables
7. Implement downgrade() function that drops all tables in correct order

Key migration details:
  - agent_registry.agent_id: UUID type
  - agent_registry.capabilities: JSON type (text in some DBs)
  - agent_registry.specializations: JSON type
  - FK from agent_performance to agent_registry on deletion (CASCADE)
  - FK from routing_decisions to agent_registry on deletion (SET NULL)
  - UNIQUE constraint on (agent_id, work_type) in agent_performance
  - Indexes on frequently-queried columns

Test migration runs:
  - `alembic upgrade head` (creates tables)
  - Verify tables exist: `\dt` in psql
  - `alembic downgrade -1` (drops tables)
  - Verify tables gone
  </action>
  <verify>
Run migration: `cd /home/james/Projects/chiffon && alembic upgrade head`.

Verify tables created: `psql chiffon -c "\dt" | grep -E "agent_registry|agent_performance|routing_decisions"`.

Should show three tables in output. Verify columns with: `psql chiffon -c "\d agent_registry"` (shows all columns, indexes, constraints).

Test downgrade: `alembic downgrade -1`, then verify tables gone: `\dt agent_registry` should return "relation does not exist".

Run upgrade again: `alembic upgrade head` (tables recreated successfully).
  </verify>
  <done>
Alembic migration created and tested. Agent registry tables (agent_registry, agent_performance, routing_decisions) created successfully in PostgreSQL. Downgrade/upgrade cycle working.
  </done>
</task>

<task type="auto">
  <name>Task 3: Implement AgentRouter in src/orchestrator/router.py</name>
  <files>src/orchestrator/router.py</files>
  <action>
Create src/orchestrator/router.py with AgentRouter class implementing intelligent agent routing.

**Class: AgentRouter**

Constructor:
  - db: Session (SQLAlchemy session)
  - logger: logging.Logger

Main method: `async def route_task(task: WorkTask, retry_count: int = 0) -> AgentSelection`
  1. Find candidate agents:
     - Query agents matching task.agent_type
     - Filter to online|idle status
     - Filter to agents with task.work_type in capabilities
     - If no candidates: raise ValueError(f"Agent pool {task.agent_type} offline/empty")

  2. Score each candidate (0-100 points):
     - Recent context bonus: +30 if agent executed same work_type in last 4 hours
     - Success rate: +40 based on perf.success_count/(success+failure) ratio
     - Specialization match: +20 if task.work_type in agent specializations
     - Load balancing: +10 - (current_load/10) (prefer less loaded agents)
     - Minimum sample size: Only use success rate if >10 total executions for work_type

  3. Select best agent (highest score)

  4. Log routing decision to RoutingDecision table

  5. Return AgentSelection with agent_id, agent_type, pool_name, selected_reason

Method: `async def dispatch_with_retry(task: WorkTask, max_retries: int = 3) -> dict`
  1. Loop up to max_retries times:
     - Call route_task(task, retry_count=attempt)
     - Dispatch work to selected agent (via RabbitMQ - reuse Phase 2 dispatch)
     - Return result on success
     - On failure: log warning, retry with retry_count incremented
  2. If all retries fail: log error, raise exception with context

Helper: `def _check_recent_context(agent_id: UUID, work_type: str, hours: int = 4) -> bool`
  - Query routing_decisions where selected_agent_id=agent_id and work_type=work_type and created_at > now()-hours
  - Return True if found (has recent context)

Helper: `def _estimate_load(agent_id: UUID) -> int`
  - Query routing_decisions for this agent in last 1 hour, count pending/executing tasks
  - Return count as load estimate (0-10 scale, cap at 10)

Helper: `def _log_routing_decision(task: WorkTask, agent: AgentRegistry, score: int, retry_count: int)`
  - Insert RoutingDecision row with:
    - task_id, work_type, agent_pool, selected_agent_id, success_rate_percent, specialization_match, recent_context_match, retried, reason

Helper: `def _calculate_success_rate(perf: AgentPerformance) -> float`
  - Return success_count / (success_count + failure_count) if total > 0 else 0.5
  - Never divide by zero

Error handling:
  - If agent pool empty: clear error message, don't retry
  - If specific agent fails: retry with different agent from pool
  - Log all routing decisions with timestamps
  - On final failure: raise ValueError with summary of attempts

Logging:
  - Info on successful routing: f"Routed {task.work_type} to {agent_id} (score={score}, context={has_context})"
  - Warning on retry: f"Attempt {attempt+1} failed, retrying on different agent"
  - Error on all retries exhausted: f"All {max_retries} attempts failed for {task.work_type}"
  </action>
  <verify>
Test import: `python -c "from src.orchestrator.router import AgentRouter; print('AgentRouter imported')"`.

Test routing (with mock agents in DB):
```python
from src.orchestrator.router import AgentRouter
from src.common.models import AgentRegistry, AgentPerformance, WorkTask

# Create test agent in DB
agent = AgentRegistry(
    agent_id=uuid4(),
    agent_type="infra",
    pool_name="pool_1",
    capabilities=["deploy_service"],
    status="online"
)
db.add(agent)
db.commit()

# Create test performance record
perf = AgentPerformance(
    agent_id=agent.agent_id,
    work_type="deploy_service",
    success_count=10,
    failure_count=2
)
db.add(perf)
db.commit()

# Test routing
router = AgentRouter(db)
task = WorkTask(order=1, name="Deploy Kuma", work_type="deploy_service", agent_type="infra", resource_requirements={...})
selection = await router.route_task(task)

assert selection.agent_id == agent.agent_id
assert selection.selected_reason  # Has explanation
print("Routing successful:", selection.model_dump())
```

Should return AgentSelection with selected agent and reason.
  </verify>
  <done>
AgentRouter class implemented with async route_task() and dispatch_with_retry() methods. Agent scoring working (success rate, context, specialization). Routing decisions logged to audit table. Error handling and retry logic in place.
  </done>
</task>

<task type="auto">
  <name>Task 4: Create comprehensive tests for agent router (tests/test_agent_router.py)</name>
  <files>tests/test_agent_router.py</files>
  <action>
Create tests/test_agent_router.py with pytest test cases covering agent routing and performance tracking.

**Test Class 1: TestAgentRouting** (async tests)
  - test_route_to_online_agent: Task routes to online agent with capability
  - test_route_prefers_higher_success_rate: Two agents available, higher success rate wins
  - test_route_prefers_recent_context: Two agents with same success rate, recent context wins
  - test_route_prefers_specialization: Two agents, specialist wins
  - test_route_balances_load: Three equal agents, less loaded agent wins
  - test_route_offline_agent_pool_fails: No online agents → ValueError with clear message
  - test_route_missing_capability_skipped: Agent without capability not considered

**Test Class 2: TestScoringAlgorithm**
  - test_success_rate_scoring: Agent with 90% success → 36 points (40 * 0.9)
  - test_context_bonus: Recent context task → +30 points
  - test_specialization_bonus: Specialist agent → +20 points
  - test_load_balancing: Less loaded agent scores higher
  - test_minimum_sample_size: Don't use success rate if <10 executions (use 0.5 default)
  - test_perfect_agent_max_score: 100 points = all bonuses + success rate

**Test Class 3: TestRoutingAudit**
  - test_routing_decision_logged: Each routing creates RoutingDecision record
  - test_routing_decision_includes_reason: RoutingDecision has explanatory reason
  - test_routing_includes_retry_flag: Retry attempts marked in routing decision
  - test_audit_queryable: Can query routing_decisions by task_id, agent_id, work_type

**Test Class 4: TestRetryLogic**
  - test_retry_on_first_agent_failure: First agent fails, retry selected different agent
  - test_max_retries_respected: Max 3 retries, stops after 3 attempts
  - test_final_retry_failure_raises: After all retries exhausted, exception raised
  - test_permanent_error_no_retry: Agent pool offline → no retry attempts
  - test_retry_count_tracked: Each attempt has retry_count=0,1,2

**Test Class 5: TestPerformanceTracking**
  - test_success_count_updated: After successful execution, agent.success_count increments
  - test_failure_count_updated: After failed execution, agent.failure_count increments
  - test_success_rate_calculated: success_rate = success / (success + failure)
  - test_last_execution_at_recorded: Timestamp of last execution recorded
  - test_difficulty_assessment_stored: Agent difficulty_assessment (straightforward|tricky|failed) stored

**Test Class 6: TestAgentRegistration**
  - test_register_new_agent: Create AgentRegistry with capabilities
  - test_agent_online_status: status="online" agents considered, offline ignored
  - test_agent_capabilities_stored: capabilities JSON list stored and queryable
  - test_specialization_optional: Can create agent without specializations

**Test Fixtures**
  - db_session: Fresh DB session for each test
  - router: AgentRouter instance
  - infra_agent_online: Online infra agent with deploy_service capability
  - infra_agent_offline: Offline infra agent (should not be routed to)
  - high_perf_agent: Agent with 95% success rate, 20 executions
  - new_agent: Agent with 1 execution (minimum sample size test)
  - deploy_task: WorkTask with work_type="deploy_service", agent_type="infra"

Use pytest fixtures, pytest.mark.asyncio for async tests, sqlalchemy in-memory DB for testing.
Test coverage: >90% of AgentRouter methods.
  </action>
  <verify>
Run: `pytest tests/test_agent_router.py -v --asyncio-mode=auto`

All tests pass (25+ test cases). Coverage report: `pytest tests/test_agent_router.py --cov=src/orchestrator/router --cov-report=term-missing`

Verify:
  - test_route_to_online_agent passes
  - test_route_prefers_higher_success_rate passes
  - test_route_offline_agent_pool_fails passes
  - test_scoring_algorithm tests pass
  - test_routing_decision_logged passes
  - test_retry_logic passes
  - All error handling tests pass

Verify audit trail: `psql chiffon -c "SELECT * FROM routing_decisions LIMIT 5"` shows recent routing decisions.
  </verify>
  <done>
Comprehensive test suite for AgentRouter with 25+ test cases covering routing, scoring, audit logging, retry logic, and performance tracking. All tests passing. Coverage >90%. Routing decisions properly logged to PostgreSQL.
  </done>
</task>

</tasks>

<verification>
**Goal-backward check:**

1. ✓ Agent registry stores capabilities and online status (AgentRegistry model)
2. ✓ Performance tracking with success rates (AgentPerformance model)
3. ✓ Routing algorithm with weighted scoring (route_task method)
4. ✓ Agent selection based on pool + performance (scoring algorithm)
5. ✓ Audit trail of all routing decisions (RoutingDecision table)

**Must-haves validation:**
- ✓ Agent registry with capabilities, specializations, status
- ✓ Performance tracking with success counts and durations
- ✓ Scoring algorithm: success_rate (40pts) + context (30pts) + specialization (20pts) + load (10pts)
- ✓ Best agent selected from pool
- ✓ Routing decisions logged to database for audit

**Integration points:**
- ✓ Takes WorkTask from Plan 03-02
- ✓ Routes to agents via RabbitMQ (Phase 2 protocol)
- ✓ Updates performance after task completion (Phase 5)
</verification>

<success_criteria>
- [ ] AgentRegistry, AgentPerformance, RoutingDecision models added to models.py
- [ ] Alembic migration created and tested (tables created in PostgreSQL)
- [ ] AgentRouter class implemented with async route_task() and dispatch_with_retry()
- [ ] Scoring algorithm correctly weighted (success rate, context, specialization, load)
- [ ] Minimum sample size enforced (only use success rate if >10 executions)
- [ ] Routing decisions logged to audit table
- [ ] All 25+ tests passing
- [ ] Coverage >90% for AgentRouter
- [ ] Error handling: offline pools detected early, clear error messages
- [ ] Retry logic: max 3 retries, permanent errors not retried
- [ ] Performance data available for future optimization
</success_criteria>

<output>
After completion, create `.planning/phases/03-orchestrator-core/03-03-SUMMARY.md` documenting:
- Database schema for agent registry and performance tracking
- AgentRouter routing algorithm and scoring formula
- Test results and coverage
- Example routing decision for "deploy_kuma" task
- Integration points for Plan 03-04 (Fallback) and Plan 03-05 (Service Integration)
</output>
