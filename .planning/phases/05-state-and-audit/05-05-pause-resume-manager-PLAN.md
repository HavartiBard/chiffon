---
phase: 05-state-and-audit
plan: 05
type: execute
wave: 1
depends_on: []
files_modified:
  - src/orchestrator/pause_manager.py
  - src/orchestrator/service.py
  - tests/test_pause_manager.py
autonomous: true
gap_closure: true

must_haves:
  truths:
    - "Orchestrator checks agent capacity before dispatching work"
    - "Work is paused if all agents below minimum capacity threshold"
    - "Paused work persists in pause_queue table and survives restart"
    - "Background polling resumes work when capacity becomes available"
    - "Pause/resume state is visible in PostgreSQL and traceable in logs"
  artifacts:
    - path: "src/orchestrator/pause_manager.py"
      provides: "PauseManager service for capacity-based pause/resume"
      exports: ["PauseManager.should_pause()", "PauseManager.resume_paused_work()"]
    - path: "src/orchestrator/service.py"
      provides: "Integration of PauseManager into dispatch_plan workflow"
      exports: ["OrchestratorService.dispatch_plan()"]
    - path: "tests/test_pause_manager.py"
      provides: "Tests for capacity checks, pause logic, resume polling"
      exports: ["TestPauseManagerCapacityCheck", "TestPauseResumeCycle"]
  key_links:
    - from: "OrchestratorService.dispatch_plan()"
      to: "PauseManager.should_pause()"
      via: "Pre-dispatch capacity check"
      pattern: "if await pause_manager.should_pause"
    - from: "PauseManager.should_pause()"
      to: "AgentRegistry.available_capacity()"
      via: "Query agent resource metrics"
      pattern: "db.query(AgentRegistry).*resource_metrics"
    - from: "PauseManager.resume_paused_work()"
      to: "pause_queue table"
      via: "Replay persisted paused tasks"
      pattern: "db.query(PauseQueueEntry)"
    - from: "PauseManager background task"
      to: "AsyncIO task loop"
      via: "Polling every N seconds"
      pattern: "asyncio.create_task.*while True.*await asyncio.sleep"
---

<objective>
**Gap Closure: Pause/Resume on Resource Constraints**

Close the gap between ORCH-04 requirement ("Orchestrator pauses/resumes execution based on available GPU resources") and current implementation (table exists but no orchestrator logic).

**Purpose:** Enable intelligent resource-aware dispatch by preventing work submission when agents are congested. Ensures reliable execution by respecting desktop agent capacity constraints and automatically resuming when resources available. Satisfies requirement for pause queue persistence across orchestrator restarts.

**Output:** PauseManager service with pre-dispatch capacity checking, pause/resume cycle management, background polling for capacity recovery, fully integrated into orchestrator dispatch flow with comprehensive tests.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/ROADMAP.md
@.planning/phases/05-state-and-audit/05-VERIFICATION.md
@.planning/phases/05-state-and-audit/05-CONTEXT.md

# Prior Plans
@.planning/phases/05-state-and-audit/05-01-SUMMARY.md
@.planning/phases/05-state-and-audit/05-02-SUMMARY.md
@.planning/phases/05-state-and-audit/05-03-SUMMARY.md

# Key source files
@src/orchestrator/service.py
@src/common/models.py
@src/orchestrator/router.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create PauseManager service for resource-aware pause/resume</name>
  <files>src/orchestrator/pause_manager.py</files>
  <action>
Create src/orchestrator/pause_manager.py (350-450 lines) implementing PauseManager class:

1. Class structure:
   - __init__(db: Session, capacity_threshold_percent: float = 0.2):
     - db: SQLAlchemy session for queries
     - capacity_threshold_percent: Minimum available capacity before pause (default 20%)
   - async should_pause(plan_id: str) -> bool - Check if work should be paused
   - async pause_work(plan_id: str, task_ids: List[str]) -> int - Persist paused work
   - async resume_paused_work() -> int - Resume queued work when capacity available
   - async start_resume_polling() -> None - Background polling task
   - stop_resume_polling() -> None - Clean shutdown

2. Capacity checking logic (should_pause):
   - Query all active agents from AgentRegistry (status='online' or online_since recent)
   - For each agent, extract available_capacity from resource_metrics JSON:
     - gpu_vram_available_gb
     - cpu_cores_available
   - Calculate pool-wide available capacity:
     - total_gpu_vram_available = sum of gpu_vram_available_gb across all agents
     - total_cpu_cores_available = sum of cpu_cores_available across all agents
   - Check if ALL agents are below threshold:
     - For each agent: available_pct = available_capacity / total_capacity * 100
     - If ALL agents < capacity_threshold_percent (default 20%), return True (pause)
     - Otherwise return False (can dispatch)
   - Log decision with agent stats: logger.info(f"Capacity check: {N} agents online, GPU avg {avg_gpu_pct}%, CPU avg {cpu_pct}%")

3. Pause work logic (pause_work):
   - Input: plan_id (string), task_ids (list of strings from WorkPlan)
   - For each task_id:
     - Create PauseQueueEntry record:
       - pause_queue_id: UUID (auto-generated)
       - task_id: from input
       - plan_id: from input
       - work_plan_json: WorkPlan JSON (need to fetch from somewhere - may need plan ref)
       - paused_at: current timestamp
       - resume_after: default null (will be set by resume logic)
     - Insert into pause_queue table
   - Log: logger.info(f"Paused {len(task_ids)} tasks from plan {plan_id} due to capacity constraints")
   - Return count of paused tasks

4. Resume work logic (resume_paused_work):
   - Query pause_queue table where resume_after IS NULL or resume_after <= now()
   - For each paused entry:
     - Check if capacity now available (using should_pause logic)
     - If capacity available:
       - Update PauseQueueEntry: mark resumed_at = now(), status = 'resumed'
       - Dispatch the work (call orchestrator.service.dispatch_plan via callback or dependency injection)
     - If still no capacity:
       - Skip, will retry on next polling cycle
       - Optionally update last_checked timestamp
   - Log: logger.info(f"Resumed {count} paused tasks, {remaining} still waiting")
   - Return count of resumed tasks

5. Background polling (start_resume_polling):
   - Create asyncio.Task that runs in background:
     ```python
     async def _resume_polling_loop():
         while self.polling_active:
             try:
                 await self.resume_paused_work()
                 await asyncio.sleep(10)  # Poll every 10 seconds
             except Exception as e:
                 logger.error(f"Resume polling error: {e}")
                 await asyncio.sleep(30)  # Backoff on error
     ```
   - Store task reference: self._polling_task
   - Log: logger.info("Resume polling started (every 10s)")

6. Graceful shutdown (stop_resume_polling):
   - Set self.polling_active = False
   - Cancel self._polling_task if active
   - Log: logger.info("Resume polling stopped")

7. Configuration:
   - Read PAUSE_CAPACITY_THRESHOLD_PERCENT from environment (default 0.2)
   - Read PAUSE_POLLING_INTERVAL_SECONDS from environment (default 10)

8. Error handling:
   - All async methods wrapped in try/except
   - Log errors but don't crash
   - Pause/resume failures don't block orchestrator
  </action>
  <verify>
1. File exists at src/orchestrator/pause_manager.py with ~400 lines
2. PauseManager class has all required methods: should_pause, pause_work, resume_paused_work, start_resume_polling, stop_resume_polling
3. Capacity threshold configurable via __init__ parameter and environment variable
4. Logging calls present for decisions and actions
5. should_pause() queries AgentRegistry and checks resource_metrics
6. pause_work() creates PauseQueueEntry records
7. resume_paused_work() queries pause_queue table
8. Background polling uses asyncio.Task and event loop
9. Graceful shutdown via stop_resume_polling()
  </verify>
  <done>
- PauseManager class created with full pause/resume logic
- Capacity checking analyzes all online agents
- Pause persistence uses PauseQueueEntry + pause_queue table
- Resume polling runs in background every 10 seconds
- Configuration via environment variables
- Comprehensive error handling and logging
  </done>
</task>

<task type="auto">
  <name>Task 2: Integrate PauseManager into orchestrator dispatch workflow</name>
  <files>src/orchestrator/service.py</files>
  <action>
Modify src/orchestrator/service.py to integrate PauseManager into dispatch flow:

1. Add PauseManager initialization:
   - Import PauseManager from orchestrator.pause_manager
   - In OrchestratorService.__init__(), create self.pause_manager = PauseManager(db_session)
   - Pass capacity_threshold_percent from config (default 0.2)
   - Start background polling on init: asyncio.create_task(self.pause_manager.start_resume_polling())

2. Pre-dispatch capacity check:
   - Find dispatch_plan() method (or where work is dispatched to agents)
   - Before calling agent.dispatch() or similar, add:
     ```python
     # Check capacity before dispatch
     if await self.pause_manager.should_pause(plan.plan_id):
         logger.warning(f"Capacity exhausted, pausing plan {plan.plan_id}")
         paused_count = await self.pause_manager.pause_work(plan.plan_id, [task.task_id for task in plan.tasks])
         # Update task status to paused
         for task in plan.tasks:
             task.status = 'paused'
         db.commit()
         return {"status": "paused", "paused_tasks": paused_count}
     ```

3. Task status handling:
   - Add 'paused' to valid task statuses in Task model (if not already present)
   - May need migration if status is ENUM type in PostgreSQL
   - When resuming from pause_queue, reset status to 'approved' or 'pending' (ready for dispatch)

4. Graceful shutdown:
   - In OrchestratorService.__del__() or shutdown handler:
     ```python
     def __del__(self):
         try:
             self.pause_manager.stop_resume_polling()
         except:
             pass
     ```
   - Or add explicit shutdown method called by FastAPI lifespan context manager

5. Logging:
   - Log on init: logger.info(f"PauseManager initialized with {capacity_threshold_percent*100}% threshold")
   - Log before pause: logger.warning(f"Pausing plan {plan_id}, {paused_count} tasks queued")
   - Log on resume: logger.info(f"Resumed {count} tasks from pause queue")

6. Configuration:
   - Read PAUSE_CAPACITY_THRESHOLD_PERCENT from environment
   - Pass to PauseManager.__init__()
  </action>
  <verify>
1. PauseManager imported in OrchestratorService
2. PauseManager instance created in __init__
3. Background polling started on init via asyncio.create_task
4. Capacity check happens before dispatch (in dispatch_plan or similar)
5. should_pause() called and result checked
6. If paused, pause_work() called and tasks marked as 'paused'
7. Graceful shutdown calls stop_resume_polling()
8. Configuration via environment variable works
9. Logging shows capacity decisions
  </verify>
  <done>
- PauseManager initialized in OrchestratorService
- Pre-dispatch capacity check integrated into dispatch_plan workflow
- Paused tasks persisted to database
- Task status set to 'paused' when queued
- Background polling started on orchestrator init
- Graceful shutdown implemented
- Configuration via environment variable
  </done>
</task>

<task type="auto">
  <name>Task 3: Create comprehensive test suite for PauseManager and integration</name>
  <files>tests/test_pause_manager.py</files>
  <action>
Create tests/test_pause_manager.py (450-550 lines) with comprehensive test coverage:

1. Test organization (use pytest classes):

   TestPauseManagerInitialization:
   - Test init with valid db session
   - Test init with capacity_threshold_percent parameter
   - Test init loads from environment variable
   - Test default threshold is 0.2 (20%)

   TestCapacityChecking:
   - Test should_pause returns False when agents have capacity
   - Test should_pause returns True when all agents below threshold
   - Test should_pause with multiple agents
   - Test should_pause with offline agents (excluded from calculation)
   - Test should_pause with mixed online/offline agents
   - Test capacity calculation: GPU and CPU handled separately
   - Test should_pause handles missing resource_metrics gracefully

   TestPauseWork:
   - Test pause_work creates PauseQueueEntry records
   - Test pause_work inserts to database
   - Test pause_work returns count of paused tasks
   - Test pause_work sets paused_at timestamp
   - Test pause_work with multiple task_ids
   - Test pause_work logs pause action

   TestResumeWork:
   - Test resume_paused_work queries pause_queue table
   - Test resume_paused_work marks entries as resumed
   - Test resume_paused_work only resumes when capacity available
   - Test resume_paused_work returns count of resumed tasks
   - Test resume_paused_work skips entries if capacity still low
   - Test resume_paused_work respects resume_after timestamp
   - Test resume_paused_work logs resume action

   TestBackgroundPolling:
   - Test start_resume_polling creates asyncio task
   - Test polling loop calls resume_paused_work every N seconds
   - Test polling continues on errors (doesn't crash)
   - Test stop_resume_polling cancels polling task
   - Test polling gracefully handles exceptions

   TestPauseResumeCycle:
   - Test full cycle: high load → pause → wait → capacity recovers → resume
   - Test multiple pauses and resumes
   - Test pause_queue survives if polling stopped (state persistence)
   - Test resume with mixed ready/waiting tasks

   TestIntegrationWithOrchestratorService:
   - Test OrchestratorService.dispatch_plan() calls should_pause()
   - Test dispatch skips if should_pause returns True
   - Test tasks marked as 'paused' in database
   - Test resume polling integrated into orchestrator lifecycle
   - Test graceful shutdown stops polling

   TestErrorHandling:
   - Test error handling when db query fails
   - Test error handling in resume polling loop
   - Test error handling when resuming fails
   - Test pause/resume failures don't crash orchestrator

2. Fixture setup:
   - Use pytest-asyncio for async test support
   - Mock AgentRegistry with test agents
   - Mock PauseQueueEntry queries
   - Create test database session fixtures
   - Create mock Task and WorkPlan objects

3. Parametrization:
   - Test multiple agent counts: 1, 3, 10 agents
   - Test various capacity scenarios: 10%, 20%, 50%, 80% utilization
   - Test multiple paused tasks: 1, 5, 20 tasks

4. Async tests:
   - Mark all tests with @pytest.mark.asyncio
   - Use async fixtures for setup
   - Properly await async methods
  </action>
  <verify>
1. File exists at tests/test_pause_manager.py with ~500 lines
2. All test classes present and runnable: pytest tests/test_pause_manager.py
3. Tests cover initialization, capacity checks, pause, resume, polling, integration, errors
4. At least 35 test methods total across all test classes
5. Parametrized tests for multiple scenarios
6. All tests passing with 100% pass rate
7. Coverage of both normal flow and error scenarios
8. Integration tests verify OrchestratorService + PauseManager interaction
  </verify>
  <done>
- Comprehensive test suite created with 35+ test methods
- Coverage: initialization, capacity checking, pause, resume, polling, integration, errors
- All tests passing with 100% pass rate
- Parametrized tests for multiple agent counts and capacity scenarios
- Integration tests verify OrchestratorService calls PauseManager correctly
- Background polling tested with async timing verification
  </done>
</task>

</tasks>

<verification>
**Functional Verification Steps:**

1. **Capacity Checking:**
   - Create mock agents with resource_metrics: GPU at 15%, 18%, 10% (all below 20% threshold)
   - Call should_pause(), verify returns True
   - Create agents with GPU at 25%, 30%, 40% (above 20%)
   - Call should_pause(), verify returns False

2. **Pause Work Creation:**
   - Call pause_work(plan_id="test-01", task_ids=["task-1", "task-2"])
   - Query pause_queue table, verify 2 PauseQueueEntry records created
   - Verify paused_at timestamp is recent (within last second)
   - Verify pause_work returns count = 2

3. **Resume Polling:**
   - Insert paused entries into pause_queue
   - Manually increase agent capacity (update resource_metrics in AgentRegistry)
   - Call resume_paused_work()
   - Verify paused entries marked as resumed_at != NULL
   - Verify return count matches resumed entries
   - Verify pause_queue entries are cleared or marked resumed

4. **Background Polling Lifecycle:**
   - Start orchestrator (which starts PauseManager polling)
   - Create low-capacity scenario (all agents <20%)
   - Dispatch a task → should be paused
   - Verify task marked as 'paused' in PostgreSQL
   - Wait 10+ seconds (polling interval)
   - Manually increase agent capacity
   - Wait another 10 seconds
   - Verify task resumed and dispatched to agent

5. **Orchestrator Restart Recovery:**
   - With paused tasks in pause_queue, stop orchestrator
   - Restart orchestrator
   - Verify pause_queue still has entries (persistence)
   - Resume polling should pick up where it left off
   - Verify no duplicate resumption

6. **Error Resilience:**
   - Force database error during pause_work
   - Verify error logged but orchestrator continues
   - Verify polling loop continues on errors (no crashes)
   - Dispatch continues even if PauseManager errors
</verification>

<success_criteria>
- Phase 5 gap 2 closed: "Pause/resume on resource constraints" now fully implemented
- PauseManager successfully checks agent capacity before dispatch
- Work is paused when all agents below 20% capacity threshold
- Paused work persists in pause_queue table and survives restart
- Background polling resumes work when capacity recovers (every 10 seconds)
- All 35+ tests passing with 100% pass rate
- ORCH-04 requirement fully satisfied: "Orchestrator pauses/resumes execution based on available GPU resources"
- Integration verified: OrchestratorService → PauseManager → pause_queue persistence → resume polling
- Capacity-aware dispatch prevents work submission during resource exhaustion
</success_criteria>

<output>
After completion, create `.planning/phases/05-state-and-audit/05-05-pause-resume-manager-SUMMARY.md` with:
- Duration, start/end times
- List of files created/modified
- Summary of pause/resume logic and polling interval
- Test results: N/N passing
- Key decisions made
- Verification of ORCH-04 requirement satisfaction
- Phase 5 completion summary (all 5 plans + 2 gap closures done)
</output>
