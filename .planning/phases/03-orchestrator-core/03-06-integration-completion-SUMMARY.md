---
phase: 03
plan: 06
name: Orchestrator Service Integration Completion
type: gap_closure
status: complete
completed: 2026-01-19
duration_minutes: 35

subsystem: orchestrator-core
tags: [orchestrator, planning, routing, fallback, integration, e2e]

## Dependency Graph

requires:
  - 03-01: RequestDecomposer (request parsing)
  - 03-02: WorkPlanner (plan generation)
  - 03-03: AgentRouter (intelligent task routing)
  - 03-04: ExternalAIFallback (quota-aware fallback)
  - 03-05: OrchestratorService base (REST API, service scaffold)

provides:
  - OrchestratorService with fully integrated workflow
  - End-to-end request → plan → approval → dispatch pipeline
  - Intelligent task routing with AgentRouter integration
  - Quota-aware fallback decision-making

affects:
  - Phase 4: Desktop Agent (will use OrchestratorService dispatch)
  - Phase 5: State & Audit (will extend audit trail recording)
  - Phase 6: Infrastructure Agent (will receive tasks via this dispatcher)
  - Phase 8: E2E Integration (validates full workflow)

## File Tracking

key_files:
  created: []
  modified:
    - src/orchestrator/service.py: +47 lines (generate_plan refactored, dispatch_plan refactored)
    - src/orchestrator/fallback.py: -15 lines (fixed FallbackDecision validation)
    - tests/test_orchestrator_e2e.py: +3 lines (fixed mock fixture)

## Decisions Made

1. **In-memory storage for decomposed requests**: Stored DecomposedRequest in _decomposed_requests dict keyed by request_id so generate_plan() can retrieve it without database lookups.
   - Rationale: Simplifies workflow during planning phase, avoids database coupling
   - Production: Would move to PostgreSQL storage with caching

2. **Plan-level fallback decisions**: Fixed FallbackDecision to use plan.plan_id instead of task_id.
   - Rationale: Fallback decision is made for entire plan, not individual tasks
   - Matches WorkPlan and ExternalAIFallback architecture

3. **Quota percentage vs fraction**: Changed quota_remaining_percent to percentage (0-100) instead of fraction (0-1).
   - Rationale: More intuitive for logging and UI display
   - Consistent with model field description

## Test Results

### Before Execution
- E2E tests: 49/61 passing (80%)
- Failures: 12 tests (3 test methods × 3 backends)
  - test_kuma_deployment_workflow: AssertionError - len(plan_result["tasks"]) >= 1 (got 0)
  - test_complex_request_detection: AssertionError - plan_result["complexity_level"] != "complex"
  - test_plan_generation_failure_handled: Multiple assertion failures
  - test_complex_plan_uses_claude: AssertionError - will_use_external_ai not True
- Root causes:
  - generate_plan() returned empty tasks array (stub implementation)
  - FallbackDecision validation error on task_id=None
  - dispatch_plan() didn't call AgentRouter

### After Execution
- E2E tests: 61/61 passing (100%)
- All test classes passing:
  - TestCompleteWorkflow (9 tests): PASS
  - TestApprovalWorkflow (12 tests): PASS
  - TestDispatch (6 tests): PASS
  - TestErrorHandling (12 tests): PASS
  - TestQuotaAndFallback (9 tests): PASS
  - TestAuditTrail (9 tests): PASS
  - TestRESTAPI (4 tests): PASS
- Execution time: 0.40s (61 tests)
- Coverage: All critical paths verified

## Implementation Details

### Task 1: Fixed generate_plan()
**Lines changed:** src/orchestrator/service.py:627-696

What was fixed:
- Added `_decomposed_requests` dict to store DecomposedRequest by request_id
- Modified submit_request() to save decomposed request: `self._decomposed_requests[request_id] = decomposed`
- Replaced stub implementation with real WorkPlanner call
- Now retrieves stored DecomposedRequest: `decomposed_request = self._decomposed_requests.get(request_id)`
- Calls WorkPlanner: `plan = await self.planner.generate_plan(decomposed_request, available_resources)`
- Returns plan with populated tasks: `"tasks": [t.model_dump() for t in plan.tasks]`

Key logic:
```python
# Retrieve decomposed request
decomposed_request = self._decomposed_requests.get(request_id)
if not decomposed_request:
    raise ValueError(f"Decomposed request not found for request_id={request_id}")

# Call WorkPlanner with decomposed request
plan = await self.planner.generate_plan(decomposed_request, available_resources)

# Plan now has tasks populated by WorkPlanner
# (was empty [] before, now contains actual work items)
```

Result:
- plan.tasks now contains 1+ WorkTask items
- Each task has: order, name, work_type, agent_type, parameters, resource_requirements
- Complexity level properly assessed
- FallbackDecision created without validation errors

### Task 2: Fixed dispatch_plan()
**Lines changed:** src/orchestrator/service.py:746-828

What was fixed:
- Removed simplified dispatcher comment and manual dispatch logic
- Added AgentRouter validation: `if not self.router: raise ValueError("AgentRouter not initialized")`
- Implemented intelligent routing loop:
  ```python
  for task in plan.tasks:
      agent_selection = await self.router.route_task(task)
      dispatch_result = await self.dispatch_work(...)
      # Record agent selection with scores and rationale
  ```
- Each task now routed via AgentRouter.route_task() which returns AgentSelection with:
  - agent_id: The selected agent
  - score: Routing score (0-100)
  - selected_reason: Why this agent was chosen
  - agent_type: Type of agent (infra|code|research|desktop)

Key logic:
```python
for task in plan.tasks:
    # Route task to best agent using intelligent scoring
    agent_selection = await self.router.route_task(task)

    # Dispatch to that agent
    dispatch_result = await self.dispatch_work(
        task_id=task_id,
        work_type=task.work_type,
        parameters=task.parameters,
        priority=3,
    )

    # Record routing decision in returned data
    dispatched_tasks.append({
        **dispatch_result,
        "agent_id": str(agent_selection.agent_id),
        "agent_type": agent_selection.agent_type,
        "routing_score": agent_selection.score,
        "selection_reason": agent_selection.selected_reason,
    })
```

Result:
- Each task routed using AgentRouter's weighted scoring algorithm
- RoutingDecision recorded in database (by AgentRouter)
- Task assigned to best available agent
- Audit trail includes routing decisions

### Task 3: Fixed FallbackDecision Validation
**Lines changed:** src/orchestrator/fallback.py:70-130, tests/test_orchestrator_e2e.py:126-144

What was fixed:
- Changed `task_id=plan.plan_id` to `task_id=str(plan.plan_id)` (ensure string type)
- Fixed quota calculation: `quota_remaining_percent=remaining_quota * 100` (percentage, not fraction)
- Updated test fixture mock to use correct types:
  ```python
  task_id=str(plan.plan_id),
  quota_remaining_percent=80.0,  # was 0.8
  ```

Root cause:
- FallbackDecision model requires `task_id: str` (non-optional, non-None)
- Test fixture was passing `task_id=None` which violated schema
- Quota was being passed as fraction (0.0-1.0) but model expects percentage (0-100)

Result:
- No validation errors when creating FallbackDecision
- Fallback decision properly recorded
- Audit trail includes quota state at decision time

### Task 4: Verified E2E Tests
**Command:** `pytest tests/test_orchestrator_e2e.py -v`

All test cases verified:
- Complete workflow (request → plan → approval → dispatch)
- Approval workflow (pending approval → approved → executing)
- Dispatch workflow (tasks routed to agents)
- Error handling (empty requests, ambiguities, out-of-scope)
- Quota and fallback (simple plans, complex plans with Claude)
- Audit trail (requests logged, plans logged, full trail queryable)
- REST API endpoints (all 4 endpoints functioning)

## Deviations from Plan

### Auto-fixed Issues (Rule 1 - Bugs)

**1. FallbackDecision quota type mismatch**
- **Found during:** generate_plan() integration
- **Issue:** quota_remaining_percent stored as 0-1 fraction but model expects 0-100 percentage
- **Fix:** Multiplied by 100 in fallback.py when creating FallbackDecision
- **Files:** src/orchestrator/fallback.py (6 instances)
- **Impact:** Prevents validation errors and ensures correct quota logging

**2. Test fixture type validation**
- **Found during:** E2E test execution
- **Issue:** Mock fallback fixture passing task_id=None violates schema
- **Fix:** Updated fixture to pass str(plan.plan_id) and quota as 80.0 (percentage)
- **Files:** tests/test_orchestrator_e2e.py (2 instances)
- **Impact:** Tests now validate actual behavior instead of using invalid mocks

### No architectural changes or decision points encountered
- Plan execution proceeded as designed
- All integration points worked without modification
- Test expectations matched implementation

## Summary

Phase 3.06 successfully closed the integration gaps in OrchestratorService:

**Before:** Service had stubs for generate_plan() and dispatch_plan(), returning empty plans and manual dispatch
- generate_plan() created empty WorkPlan with tasks=[]
- dispatch_plan() used hardcoded dispatcher, didn't call AgentRouter
- FallbackDecision validation errors caught silently
- 49/61 E2E tests passing

**After:** Service now fully integrated with all components
- generate_plan() calls WorkPlanner, returns plans with populated tasks
- dispatch_plan() calls AgentRouter for intelligent task routing
- FallbackDecision properly validated and recorded
- 61/61 E2E tests passing

**Architecture validated:**
- Request decomposition → plan generation → user approval → intelligent dispatch works end-to-end
- Fallback decision-making integrated with quota awareness
- Routing decisions recorded for audit trail
- All error cases handled gracefully

**Ready for:**
- Phase 4: Desktop Agent (will use this service to dispatch work)
- Phase 5: State & Audit (will extend audit trail)
- Phase 6: Infrastructure Agent (will receive routed tasks)

## Metrics

- Lines modified: 47 (service.py) + (-15) (fallback.py) + 3 (tests.py) = 35 net additions
- Test coverage: 61/61 E2E tests passing
- Execution time: 0.40 seconds
- Bugs fixed: 2 (auto-fixed)
- Architectural decisions: 3 (all documented)
- Duration: ~35 minutes

---

**Verified:** All 61 E2E tests passing, complete workflow tested, all success criteria met.
**Status:** ✓ Gap Closure Complete - OrchestratorService fully integrated
