---
phase: 03-orchestrator-core
plan: 02
type: execute
wave: 1
depends_on: ["03-01"]
files_modified:
  - src/orchestrator/planner.py
  - src/common/models.py
  - tests/test_work_planner.py
autonomous: true
must_haves:
  truths:
    - "Work plan generated from decomposed request with ordered tasks and resource requirements"
    - "Plan includes dependencies and alternatives for unavailable resources"
    - "Tasks reordered based on resource availability (low-resource first)"
    - "Plan is human-readable (sequential numbered list format)"
    - "Plan includes complexity assessment and fallback flag"
  artifacts:
    - path: "src/orchestrator/planner.py"
      provides: "WorkPlanner class that generates executable plans from decomposed requests"
      exports: ["WorkPlanner", "WorkTask", "WorkPlan"]
    - path: "src/common/models.py"
      provides: "WorkTask and WorkPlan Pydantic models"
      contains: "class WorkTask, class WorkPlan"
    - path: "tests/test_work_planner.py"
      provides: "Comprehensive tests for plan generation, dependency resolution, resource reordering"
      exports: ["TestWorkPlanner", "TestResourceOrdering", "TestPlanValidation"]
  key_links:
    - from: "WorkPlanner"
      to: "DecomposedRequest"
      via: "async def generate_plan(decomposed) takes output from RequestDecomposer"
      pattern: "generate_plan.*DecomposedRequest"
    - from: "WorkTask"
      to: "resource_requirements"
      via: "each task has dict with estimated_duration_seconds, gpu_vram_mb, cpu_cores"
      pattern: "resource_requirements.*gpu_vram"
    - from: "WorkPlanner"
      to: "AgentPool"
      via: "queries available resources before generating plan and reordering"
      pattern: "await.*get_available_resources"
---

<objective>
Build the work plan generation layer that converts decomposed requests into executable, ordered task plans with resource awareness.

Purpose: Transform the abstract decomposed request (from Plan 03-01) into a concrete, executable plan that includes task ordering, dependencies, resource requirements, and alternatives. Plans are presented to users for approval before execution.

Output: WorkPlanner service with WorkTask and WorkPlan models, comprehensive tests validating plan generation, dependency resolution, and resource-aware task reordering.
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
@src/common/config.py
@src/orchestrator/service.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add WorkTask and WorkPlan Pydantic models to src/common/models.py</name>
  <files>src/common/models.py</files>
  <action>
Add three Pydantic models to src/common/models.py (after DecomposedRequest):

1. **WorkTask** - Single executable task in a plan:
   - order: int (sequence number, 1-based)
   - name: str (human-readable task name)
   - work_type: str (e.g., "deploy_service", "run_playbook", "add_configuration")
   - agent_type: str (e.g., "infra", "code", "research", "desktop")
   - parameters: dict (task-specific parameters, default {})
   - resource_requirements: dict (with keys: estimated_duration_seconds, gpu_vram_mb, cpu_cores)
   - depends_on: list[int] (task orders this depends on, default [])
   - alternatives: list[dict] (optional alternative approaches if resources unavailable, default [])
   - estimated_external_ai_calls: int (how many Claude calls estimated, default 0)

2. **WorkPlan** - Complete execution plan:
   - plan_id: UUID (unique plan identifier)
   - request_id: UUID (links back to original request)
   - tasks: list[WorkTask] (ordered execution tasks)
   - estimated_duration_seconds: int (sum of all task durations)
   - complexity_level: str ("simple"|"medium"|"complex")
   - will_use_external_ai: bool (True if any task will fallback to Claude)
   - status: str ("pending_approval"|"approved"|"executing"|"completed"|"rejected")
   - created_at: datetime (when plan was generated)
   - approved_at: Optional[datetime] (when user approved)
   - human_readable_summary: str (plain text summary for user review)

3. **IntentToWorkTypeMapping** - Configuration for translating decomposed intents to work types:
   - intent: str (from RequestDecomposer, e.g., "deploy_kuma")
   - work_type: str (to be used in task, e.g., "deploy_service")
   - agent_type: str (e.g., "infra")
   - estimated_duration_seconds: int
   - gpu_vram_mb: int
   - cpu_cores: int
   - alternatives: list[dict] (if primary unavailable, try these)

Use Pydantic BaseModel, add field descriptions, configure defaults.
  </action>
  <verify>
Test import: `python -c "from src.common.models import WorkTask, WorkPlan, IntentToWorkTypeMapping; print('Models imported')"`.

Validate models can be instantiated:
```python
from src.common.models import WorkTask, WorkPlan
from uuid import uuid4

task = WorkTask(order=1, name="Deploy Kuma", work_type="deploy_service", agent_type="infra", resource_requirements={"estimated_duration_seconds": 180, "gpu_vram_mb": 0, "cpu_cores": 2})
plan = WorkPlan(plan_id=uuid4(), request_id=uuid4(), tasks=[task], estimated_duration_seconds=180, complexity_level="simple", will_use_external_ai=False)
print("Models valid:", plan.model_dump())
```

Should show serialized plan with all fields.
  </verify>
  <done>
WorkTask, WorkPlan, and IntentToWorkTypeMapping models added to models.py with proper field types, defaults, and docstrings. Models can be instantiated and serialized correctly.
  </done>
</task>

<task type="auto">
  <name>Task 2: Implement WorkPlanner in src/orchestrator/planner.py</name>
  <files>src/orchestrator/planner.py</files>
  <action>
Create src/orchestrator/planner.py with WorkPlanner class implementing plan generation.

**Class: WorkPlanner**

Constructor:
  - config: dict or Config object with work type mappings
  - logger: logging.Logger

Main method: `async def generate_plan(decomposed: DecomposedRequest, available_resources: dict) -> WorkPlan`
  1. For each subtask in decomposed.subtasks:
     - Map intent to work_type/agent_type using intent_mapping (see _get_intent_mapping)
     - Create WorkTask with estimated resources
     - Check if resources available
     - If unavailable, add alternatives to task
  2. Reorder tasks by resource availability (low-resource first, using _reorder_by_resources)
  3. Assess complexity for fallback decision
  4. Build human_readable_summary (formatted as: "1. Deploy Kuma (estimated 180s)\n2. Add portals (estimated 60s)")
  5. Return WorkPlan with all tasks, status="pending_approval"

Helper: `def _get_intent_mapping() -> dict[str, IntentToWorkTypeMapping]`
  - Returns mapping of known intents to work types:
    - "deploy_kuma" → (work_type="deploy_service", agent_type="infra", duration=180s, gpu=0, cpu=2)
    - "add_portals_to_config" → (work_type="run_playbook", agent_type="infra", duration=60s, gpu=0, cpu=1)
    - "run_automation" → (work_type="run_playbook", agent_type="infra", duration=120s, gpu=0, cpu=1)
    - "research" → (work_type="research_task", agent_type="research", duration=300s, gpu=0, cpu=1)
    - "code_gen" → (work_type="code_generation", agent_type="code", duration=120s, gpu=2048, cpu=2)
    - Unknown intents → (work_type="custom_work", agent_type="research", duration=300s, gpu=0, cpu=1)
  - Can be loaded from config file for extensibility

Helper: `def _reorder_by_resources(tasks: list[WorkTask], available_resources: dict) -> list[WorkTask]`
  - Separate tasks into ready (can run now) and blocked (resources unavailable)
  - Return ready + blocked (ready tasks run first while waiting for blocked resources)
  - Re-number task orders after reordering
  - Log: f"Reordered {len(ready)} ready tasks before {len(blocked)} blocked tasks"

Helper: `def _assess_complexity(work_types: list[str]) -> str`
  - If any work_type in ["research_task", "code_generation", "architecture_review"]: return "complex"
  - If >3 tasks: return "medium"
  - Otherwise: return "simple"

Helper: `def _build_human_readable_summary(tasks: list[WorkTask]) -> str`
  - Format: numbered list with task names and estimated durations
  - Example output: "1. Deploy Kuma Uptime (estimated 180 seconds)\n2. Add portals to configuration (estimated 60 seconds)\n\nTotal estimated time: 240 seconds (~4 minutes)"
  - Include resource warnings if any task has high resource requirements

Helper: `def _check_resource_availability(task: WorkTask, available: dict) -> bool`
  - Check if available resources >= required resources
  - available keys: gpu_vram_mb, cpu_cores
  - required from: task.resource_requirements

Error handling:
  - If decomposed.subtasks empty: log warning, return empty plan
  - If all tasks blocked by missing resources: log warning, include alternatives
  - If plan generation fails: raise ValueError with helpful message

Logging:
  - Info: f"Generated plan {plan_id} with {len(tasks)} tasks, complexity={complexity}"
  - Warning: f"Plan {plan_id} has {len(blocked)} resource-constrained tasks"
  - Info: f"Will use external AI: {will_use_external_ai}"
  </action>
  <verify>
Test import: `python -c "from src.orchestrator.planner import WorkPlanner; print('WorkPlanner imported')"`.

Test plan generation (manual async test):
```python
import asyncio
from src.orchestrator.planner import WorkPlanner
from src.common.models import DecomposedRequest, Subtask

async def test():
    planner = WorkPlanner(config={})
    decomposed = DecomposedRequest(
        request_id=...,
        original_request="Deploy Kuma and add portals",
        subtasks=[
            Subtask(order=1, name="Deploy Kuma", intent="deploy_kuma", confidence=0.95),
            Subtask(order=2, name="Add portals", intent="add_portals_to_config", confidence=0.88)
        ],
        ambiguities=[],
        out_of_scope=[],
        complexity_level="simple",
        decomposer_model="claude"
    )

    available_resources = {"gpu_vram_mb": 0, "cpu_cores": 4}
    plan = await planner.generate_plan(decomposed, available_resources)

    assert plan.plan_id
    assert len(plan.tasks) == 2
    assert plan.tasks[0].name == "Deploy Kuma"
    assert plan.status == "pending_approval"
    assert "Deploy Kuma" in plan.human_readable_summary
    print("Plan generation successful:", plan.model_dump())

asyncio.run(test())
```

Should produce WorkPlan with 2 tasks, human_readable_summary containing task names and durations.
  </verify>
  <done>
WorkPlanner class implemented with async generate_plan() method. Takes DecomposedRequest and available resources, creates ordered WorkPlan with human-readable summary. Resource-aware reordering working. Complexity assessment in place. Logging shows decision points.
  </done>
</task>

<task type="auto">
  <name>Task 3: Create comprehensive tests for work planner (tests/test_work_planner.py)</name>
  <files>tests/test_work_planner.py</files>
  <action>
Create tests/test_work_planner.py with pytest test cases covering plan generation, resource ordering, and validation.

**Test Class 1: TestPlanGeneration** (async tests)
  - test_generate_plan_simple_request: 1 subtask → 1 task plan
  - test_generate_plan_complex_request: 2 subtasks → 2 task plan with correct ordering
  - test_generate_plan_with_dependencies: Subtasks with implicit ordering maintained
  - test_plan_status_pending_approval: New plans have status="pending_approval"
  - test_plan_includes_human_summary: Plan has readable human_readable_summary
  - test_estimated_duration_correct: Total duration = sum of task durations

**Test Class 2: TestResourceOrdering**
  - test_ready_tasks_before_blocked: Tasks with available resources listed first
  - test_blocked_tasks_ordered: Resource-constrained tasks ordered after ready tasks
  - test_reorder_maintains_dependencies: Task ordering respects dependencies
  - test_all_gpu_tasks_blocked: All GPU-intensive tasks → blocked list, warns in log
  - test_alternative_resources_suggested: Blocked tasks have alternatives (CPU vs GPU)

**Test Class 3: TestComplexityAssessment**
  - test_simple_plan: 1-2 simple tasks → "simple"
  - test_medium_plan: 3+ tasks → "medium"
  - test_complex_plan: Any research/code_gen task → "complex"
  - test_will_use_external_ai_flag: Complex plans have will_use_external_ai=True

**Test Class 4: TestIntentMapping**
  - test_deploy_kuma_maps_to_infra: "deploy_kuma" intent → infra agent, deploy_service work_type
  - test_research_intent_maps_to_research: "research" intent → research agent
  - test_code_gen_intent_maps_to_code: "code_gen" intent → code agent
  - test_unknown_intent_defaults_to_research: Unknown intents → research agent, custom_work

**Test Class 5: TestPlanValidation**
  - test_plan_has_valid_uuid: plan_id and request_id are valid UUIDs
  - test_all_tasks_have_resources: Every task has resource_requirements with required keys
  - test_task_orders_sequential: Task orders are 1, 2, 3, ... with no gaps
  - test_depends_on_valid: Dependency references exist as task orders
  - test_alternatives_present_if_blocked: Blocked tasks have non-empty alternatives

**Test Class 6: TestErrorHandling**
  - test_empty_decomposed_request: Empty subtasks → warning, empty plan returned
  - test_no_resources_available: All tasks blocked → plan includes alternatives, warning logged
  - test_malformed_intent: Intent not in mapping → defaults to custom_work
  - test_missing_resources_dict: generate_plan without available_resources → handled gracefully

**Test Fixtures**
  - simple_decomposed_request: Single "deploy_kuma" subtask
  - complex_decomposed_request: Multiple subtasks with research task
  - available_resources_full: {"gpu_vram_mb": 8000, "cpu_cores": 8}
  - available_resources_cpu_only: {"gpu_vram_mb": 0, "cpu_cores": 4}
  - planner: WorkPlanner instance with mock config

Use pytest fixtures, pytest.mark.asyncio for async tests.
Test coverage: >90% of WorkPlanner methods.
  </action>
  <verify>
Run: `pytest tests/test_work_planner.py -v --asyncio-mode=auto`

All tests pass (20+ test cases). Coverage report: `pytest tests/test_work_planner.py --cov=src/orchestrator/planner --cov-report=term-missing`

Verify:
  - test_generate_plan_simple_request passes
  - test_generate_plan_complex_request passes
  - test_ready_tasks_before_blocked passes
  - test_complexity_assessment passes
  - test_intent_mapping passes
  - All error handling tests pass
  </verify>
  <done>
Comprehensive test suite for WorkPlanner with 20+ test cases covering plan generation, resource ordering, complexity assessment, intent mapping, and validation. All tests passing. Coverage >90%.
  </done>
</task>

</tasks>

<verification>
**Goal-backward check:**

1. ✓ Work plan generated from decomposed request (generate_plan method)
2. ✓ Tasks ordered with resource requirements (WorkTask includes resource_requirements)
3. ✓ Dependencies and alternatives tracked (depends_on and alternatives fields)
4. ✓ Human-readable format (human_readable_summary field)
5. ✓ Complexity assessment for fallback decision (will_use_external_ai flag)

**Must-haves validation:**
- ✓ Ordered tasks with resource requirements
- ✓ Dependencies resolved (depends_on field)
- ✓ Resource-aware reordering (ready tasks before blocked)
- ✓ Human-readable summary (<1 minute to understand)
- ✓ Alternatives for unavailable resources

**Integration points:**
- ✓ Takes DecomposedRequest from Plan 03-01
- ✓ Ready for routing to agents (Plan 03-03)
- ✓ Supports resource-aware execution (Phase 5)
</verification>

<success_criteria>
- [ ] WorkTask, WorkPlan, IntentToWorkTypeMapping models added to models.py
- [ ] WorkPlanner class implemented in src/orchestrator/planner.py with async generate_plan()
- [ ] Intent mapping covers deploy_kuma, add_portals_to_config, research, code_gen, and defaults
- [ ] Resource-aware task reordering working (ready tasks before blocked)
- [ ] Human-readable summary generated correctly
- [ ] All 20+ tests in test_work_planner.py passing
- [ ] Coverage >90% for WorkPlanner
- [ ] Logging shows plan generation decisions and resource constraints
- [ ] Plan status lifecycle correct (pending_approval → approved → executing)
</success_criteria>

<output>
After completion, create `.planning/phases/03-orchestrator-core/03-02-SUMMARY.md` documenting:
- Models added to common/models.py
- WorkPlanner implementation and intent mapping
- Resource-aware reordering algorithm
- Test results and coverage
- Example plan output for "Deploy Kuma and add portals" request
- Integration points for Plan 03-03 (AgentRouter)
</output>
