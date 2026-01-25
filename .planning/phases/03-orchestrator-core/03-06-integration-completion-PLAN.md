---
phase: 03-orchestrator-core
plan: 06
type: gap_closure
wave: 3
depends_on: ["03-01", "03-02", "03-03", "03-04", "03-05"]
gap_closure: true
files_modified:
  - src/orchestrator/service.py
  - tests/test_orchestrator_e2e.py
autonomous: true
must_haves:
  truths:
    - "OrchestratorService.generate_plan() calls WorkPlanner to create real work plans with tasks"
    - "OrchestratorService.dispatch_plan() calls AgentRouter to select best agent for each task"
    - "Complete workflow test: request → parse → plan with tasks → approve → dispatch via router → audit passes"
    - "FallbackDecision validation errors handled gracefully"
    - "All E2E tests pass (61/61)"
  artifacts:
    - path: "src/orchestrator/service.py"
      provides: "Fixed generate_plan() and dispatch_plan() methods that call integrated services"
      exports: ["OrchestratorService"]
    - path: "tests/test_orchestrator_e2e.py"
      provides: "All E2E tests passing, including complete workflow and error cases"
      exports: ["TestOrchhestratorE2E"]
---

# Phase 3.06: Orchestrator Service Integration Completion

## Objective

Complete the OrchestratorService integration layer to wire RequestDecomposer, WorkPlanner, AgentRouter, and ExternalAIFallback together. Currently, generate_plan() and dispatch_plan() are stubs. This plan closes those gaps.

## Tasks

### Task 1: Fix OrchestratorService.generate_plan()

**Current State:** Creates empty WorkPlan with tasks=[], has comment "For now..."

**Required Changes:**
1. Retrieve or create DecomposedRequest (currently stubbed as `decomposed_request = None`)
2. Call `await self.decomposer.decompose(request.request_text)` to get actual DecomposedRequest
3. Call `await self.planner.generate_plan(decomposed_request, self.available_resources)` to get WorkPlan with tasks
4. Verify plan.tasks is populated (len > 0) before returning
5. Call fallback check properly: `await self.fallback.should_use_external_ai(plan)` (plan_id not task_id)

**Success Criteria:**
- generate_plan() returns WorkPlan with 1+ tasks
- Tasks contain estimated duration, resource requirements, agent type
- Complexity assessment drives fallback decision
- FallbackDecision created without validation errors

### Task 2: Fix OrchestratorService.dispatch_plan()

**Current State:** Has comment "simplified dispatcher", creates manual dispatch, does NOT call AgentRouter

**Required Changes:**
1. Remove the "simplified" dispatcher logic
2. For each task in plan.tasks: call `await self.router.route_task(task)` to get AgentSelection
3. Publish task to RabbitMQ using agent_id from AgentSelection
4. Record RoutingDecision in database (router already does this)
5. Return dispatch confirmation with task assignments

**Success Criteria:**
- Each task routed via AgentRouter.route_task()
- AgentSelection.agent_id is used for MQ dispatch
- RoutingDecision recorded for audit trail
- All tasks dispatch successfully (no orphaned tasks)

### Task 3: Fix FallbackDecision Validation

**Current State:** Validation errors caught silently on task_id None

**Required Changes:**
1. FallbackDecision should use plan_id (not task_id) since it's a plan-level decision
2. Update Pydantic model validation to handle None gracefully OR
3. Pass correct plan_id when creating FallbackDecision

**Success Criteria:**
- FallbackDecision creation doesn't log warnings
- Fallback decision properly recorded in database
- No validation errors on plan-level fallback decisions

### Task 4: Re-run E2E Tests

**Current State:** 49/61 passing; 12 failures related to empty tasks

**Required Changes:**
1. Run full E2E test suite: `pytest tests/test_orchestrator_e2e.py -v`
2. Verify TestCompleteWorkflow tests pass (kuma_deployment_workflow, code_generation, etc.)
3. Verify TestErrorHandling and TestQuotaAndFallback pass
4. Fix any remaining failures (should be 0 after tasks 1-3)

**Success Criteria:**
- 61/61 E2E tests passing
- Complete workflow test covers: request → decompose → plan with tasks → approve → dispatch
- All error scenarios handled gracefully

## Deviations & Edge Cases

**If generate_plan() needs DecomposedRequest from DB:**
- Check if decomposed_request already in database from decompose step
- If not, retrieve from cache or decompose again (idempotent)

**If AgentRouter has no available agents:**
- Fallback: use default agent for work type
- Log decision with reason "no agents available"

**If MQ dispatch fails:**
- Retry up to 3 times (already implemented in dispatch_with_retry)
- Log failure with context for post-mortem

## Definition of Done

- [ ] OrchestratorService.generate_plan() calls WorkPlanner and returns plan with tasks
- [ ] OrchestratorService.dispatch_plan() calls AgentRouter for each task
- [ ] FallbackDecision created without validation errors
- [ ] All 61 E2E tests passing
- [ ] SUMMARY.md created
- [ ] Changes committed with atomic commits
