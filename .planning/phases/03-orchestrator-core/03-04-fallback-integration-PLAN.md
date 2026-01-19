---
phase: 03-orchestrator-core
plan: 04
type: execute
wave: 2
depends_on: ["03-01", "03-02", "03-03"]
files_modified:
  - src/orchestrator/fallback.py
  - src/common/models.py
  - tests/test_fallback_integration.py
autonomous: true
must_haves:
  truths:
    - "Orchestrator checks LiteLLM quota before executing complex tasks"
    - "Complexity assessment determines if local Ollama sufficient or need Claude"
    - "External AI (Claude) called when quota <20% OR complexity=complex"
    - "Claude failures fall back to Ollama; both failures raise exception"
    - "All external AI usage logged in Task.external_ai_used for audit trail"
  artifacts:
    - path: "src/orchestrator/fallback.py"
      provides: "ExternalAIFallback class with should_use_external_ai() and call_with_fallback()"
      exports: ["ExternalAIFallback", "FallbackDecision"]
    - path: "src/common/models.py"
      provides: "FallbackDecision Pydantic model for tracking fallback decisions"
      contains: "class FallbackDecision"
    - path: "tests/test_fallback_integration.py"
      provides: "Tests for quota checks, fallback triggers, Claude/Ollama failures"
      exports: ["TestFallbackTriggers", "TestFallbackErrors", "TestQuotaTracking"]
  key_links:
    - from: "ExternalAIFallback"
      to: "LiteLLMClient"
      via: "checks quota via get_user_quota(), calls via call_llm()"
      pattern: "await self.llm.get_user_quota.*await self.llm.call_llm"
    - from: "ExternalAIFallback"
      to: "Task"
      via: "logs external_ai_used decision to task record"
      pattern: "task.external_ai_used.*\\{model.*timestamp"
    - from: "WorkPlan"
      to: "should_use_external_ai"
      via: "checks plan.complexity_level to determine if Claude needed"
      pattern: "plan.complexity_level.*complex"
---

<objective>
Build the external AI fallback layer that manages Claude/Ollama routing with quota awareness and graceful failure handling.

Purpose: Enable intelligent fallback to Claude when local reasoning (Ollama) is insufficient or quota allows, while maintaining cost discipline. Track quota consumption, assess task complexity, implement three-tier fallback (Claude → Ollama → exception), and log all decisions for post-mortem analysis.

Output: ExternalAIFallback service with quota checks, complexity assessment, fallback logic, and comprehensive tests validating fallback triggers, error scenarios, and cost tracking.
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
@src/common/litellm_client.py
@src/common/config.py
@src/common/models.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add FallbackDecision model to src/common/models.py</name>
  <files>src/common/models.py</files>
  <action>
Add FallbackDecision Pydantic model to src/common/models.py (after RequestParsingConfig):

**FallbackDecision** - Tracks fallback decision for a task:
  - task_id: UUID (which task this applies to)
  - decision: str ("use_claude"|"use_ollama"|"no_fallback") (what was decided)
  - reason: str (why: "quota_critical"|"high_complexity"|"local_sufficient"|"claude_failed")
  - quota_remaining_percent: float (0.0-1.0, quota status at decision time)
  - complexity_level: str ("simple"|"medium"|"complex", task complexity)
  - fallback_tier: int (0=primary Claude, 1=fallback Ollama, 2=failure)
  - model_used: str (which LLM was actually used: "claude-opus-4.5"|"ollama/neural-chat")
  - tokens_used: Optional[int] (token count if available from LLM)
  - cost_usd: Optional[float] (estimated cost if available)
  - error_message: Optional[str] (error if fallback occurred)
  - created_at: datetime

Use Pydantic BaseModel with helpful docstrings, sensible defaults.
  </action>
  <verify>
Test import: `python -c "from src.common.models import FallbackDecision; print('FallbackDecision imported')"`.

Verify instantiation:
```python
from src.common.models import FallbackDecision
from uuid import uuid4
from datetime import datetime

decision = FallbackDecision(
    task_id=uuid4(),
    decision="use_claude",
    reason="high_complexity",
    quota_remaining_percent=0.85,
    complexity_level="complex",
    fallback_tier=0,
    model_used="claude-opus-4.5"
)
print("Model valid:", decision.model_dump())
```

Should show all fields properly serialized.
  </verify>
  <done>
FallbackDecision model added to models.py with proper Pydantic configuration. Can be instantiated and serialized correctly.
  </done>
</task>

<task type="auto">
  <name>Task 2: Implement ExternalAIFallback in src/orchestrator/fallback.py</name>
  <files>src/orchestrator/fallback.py</files>
  <action>
Create src/orchestrator/fallback.py with ExternalAIFallback class implementing quota-aware external AI logic.

**Class: ExternalAIFallback**

Constructor:
  - litellm_client: LiteLLMClient (from common.litellm_client)
  - config: Config (from common.config)
  - db: Session (SQLAlchemy session for logging)
  - logger: logging.Logger

Main method: `async def should_use_external_ai(plan: WorkPlan) -> tuple[FallbackDecision, bool]`
  1. Check quota first (fastest):
     - Call _get_remaining_quota()
     - If <20%: return (FallbackDecision(decision="use_claude", reason="quota_critical"), True)
  2. Check complexity (from plan.complexity_level):
     - If complexity == "complex": return (FallbackDecision(decision="use_claude", reason="high_complexity"), True)
     - Otherwise: return (FallbackDecision(decision="use_ollama", reason="local_sufficient"), False)
  3. Log decision to audit trail

Method: `async def call_external_ai_with_fallback(prompt: str, task_context: dict) -> dict`
  1. Determine if should use Claude (call should_use_external_ai)
  2. Tier 1 - Try Claude:
     - If should_use_claude: call llm.call_llm(model="claude-opus-4.5", ...)
     - On success: return response, log usage
     - On timeout/error: continue to Tier 2
  3. Tier 2 - Try Ollama (fallback):
     - Call llm.call_llm(model="ollama/neural-chat", ...)
     - On success: return response, log usage, log fallback occurred
     - On error: continue to Tier 3
  4. Tier 3 - Failure:
     - Both failed: raise Exception("Both Claude and Ollama failed: {error}")
     - Log failure attempt with error details

Method: `async def _get_remaining_quota() -> float`
  1. Try to get user quota via LiteLLMClient:
     - Call llm.get_user_quota(api_key=config.LITELLM_MASTER_KEY)
     - Calculate: remaining_budget = max(0, max_budget - total_spend)
     - Return: remaining_fraction = remaining_budget / max_budget (0.0-1.0)
  2. On error (LiteLLM unavailable):
     - Log warning: f"Could not check quota: {e}; defaulting to Ollama (safe)"
     - Return 1.0 (assume unlimited, use Ollama)

Helper: `def _log_fallback_decision(decision: FallbackDecision, task_id: UUID)`
  - Insert FallbackDecision record to database
  - Log to application logger: f"Fallback: {decision.decision} due to {decision.reason}"

Helper: `async def _log_llm_usage(model: str, task_context: dict, tokens: int, cost: float)`
  - Update Task record with external_ai_used = {model, timestamp, tokens, cost_usd}
  - Log: f"Used {model} for task {task_id}: {tokens} tokens, ${cost:.4f}"

Error handling:
  - TimeoutError on Claude → log warning, fall back to Ollama
  - RateLimitError on Claude → log warning, fall back to Ollama
  - Any other error → try Ollama, then fail if both error
  - Catch JSONDecodeError if LLM response malformed → raise ValueError("Invalid response format")
  - Gracefully handle quota API unavailability (default to Ollama)

Logging:
  - Info on quota check: f"Quota check: {quota:.1%} remaining"
  - Warning on low quota: f"Quota critical: {quota:.1%} remaining, using Claude"
  - Info on Claude call: f"Called Claude for {task_context.get('name')}"
  - Warning on Claude failure: f"Claude failed, falling back to Ollama: {error}"
  - Info on Ollama fallback: f"Using Ollama fallback for {task_context.get('name')}"
  - Error on all failure: f"Both Claude and Ollama failed for {task_id}"

Configuration:
  - QUOTA_THRESHOLD_PERCENT: 20 (trigger Claude if <20%)
  - CLAUDE_TIMEOUT_SECONDS: 30 (Claude max wait time)
  - OLLAMA_TIMEOUT_SECONDS: 15 (Ollama max wait time)
  - Load from config.py, allow override via environment
  </action>
  <verify>
Test import: `python -c "from src.orchestrator.fallback import ExternalAIFallback; print('ExternalAIFallback imported')"`.

Test fallback decision (manual async test):
```python
import asyncio
from src.orchestrator.fallback import ExternalAIFallback
from src.common.models import WorkPlan

async def test():
    fallback = ExternalAIFallback(llm_client, config, db_session)

    # Test 1: Simple plan should not trigger fallback
    simple_plan = WorkPlan(..., complexity_level="simple", will_use_external_ai=False)
    decision, use_claude = await fallback.should_use_external_ai(simple_plan)
    assert decision.decision == "use_ollama"
    assert use_claude == False
    print("Test 1 passed: Simple plan uses Ollama")

    # Test 2: Complex plan should trigger fallback
    complex_plan = WorkPlan(..., complexity_level="complex", will_use_external_ai=True)
    decision, use_claude = await fallback.should_use_external_ai(complex_plan)
    assert decision.decision == "use_claude"
    assert use_claude == True
    print("Test 2 passed: Complex plan triggers Claude")

    # Test 3: Low quota should trigger Claude
    mock_quota_result = {"remaining_fraction": 0.15}  # 15% remaining
    decision, use_claude = await fallback.should_use_external_ai(simple_plan)  # quota <20%
    assert decision.reason == "quota_critical"
    print("Test 3 passed: Low quota triggers Claude")

asyncio.run(test())
```

Should show fallback decisions being made based on quota and complexity.
  </verify>
  <done>
ExternalAIFallback class implemented with async should_use_external_ai() and call_external_ai_with_fallback() methods. Quota checking working. Three-tier fallback (Claude → Ollama → exception) implemented. Decision logging in place.
  </done>
</task>

<task type="auto">
  <name>Task 3: Create comprehensive tests for fallback integration (tests/test_fallback_integration.py)</name>
  <files>tests/test_fallback_integration.py</files>
  <action>
Create tests/test_fallback_integration.py with pytest test cases covering fallback logic and error scenarios.

**Test Class 1: TestFallbackTriggers** (async tests)
  - test_simple_plan_no_fallback: Simple complexity + high quota → use Ollama
  - test_complex_plan_triggers_claude: Complex complexity → trigger Claude
  - test_low_quota_triggers_claude: Quota <20% → trigger Claude regardless of complexity
  - test_high_quota_simple_plan: Quota >20% + simple → use Ollama
  - test_quota_exactly_20_percent: Edge case: quota=20% exactly → use Claude
  - test_quota_19_percent: Quota=19% → use Claude

**Test Class 2: TestQuotaTracking**
  - test_get_remaining_quota_success: Successfully retrieve quota from LiteLLM
  - test_get_remaining_quota_unavailable: LiteLLM unavailable → default to Ollama
  - test_quota_percentage_calculated: Budget 1000, spent 750, quota=25%
  - test_quota_zero_remaining: Budget 1000, spent 1000, quota=0% → Claude
  - test_quota_negative_handled: Budget 1000, spent 1100 (overage) → quota=0%, use Claude
  - test_quota_check_logged: Quota check recorded in FallbackDecision

**Test Class 3: TestClaudeFailover**
  - test_claude_success: Claude call succeeds → return response
  - test_claude_timeout_falls_back: Claude times out → fall back to Ollama
  - test_claude_rate_limit_falls_back: Claude rate limit → fall back to Ollama
  - test_claude_invalid_response_fails: Claude returns invalid JSON → raises ValueError
  - test_claude_usage_logged: Successful Claude call logged with tokens, cost

**Test Class 4: TestOllamaFallback**
  - test_ollama_success: Ollama call succeeds → return response
  - test_ollama_failure_raises: Ollama fails after Claude fails → raises Exception
  - test_ollama_timeout_raises: Ollama timeout → raises TimeoutError
  - test_ollama_usage_logged: Successful Ollama call logged

**Test Class 5: TestBothTiersFail**
  - test_both_claude_and_ollama_fail: Both tiers fail → Exception with context
  - test_error_message_includes_context: Exception includes task context
  - test_final_error_logged: Failure logged to audit trail with error details

**Test Class 6: TestComplexityAssessment**
  - test_assess_complexity_simple: 1-2 simple tasks → no fallback
  - test_assess_complexity_medium: 3+ tasks → may trigger fallback
  - test_assess_complexity_research: "research" task → complex, fallback
  - test_assess_complexity_code_gen: "code_gen" task → complex, fallback

**Test Class 7: TestAuditLogging**
  - test_fallback_decision_recorded: Decision stored in FallbackDecision table
  - test_fallback_reason_logged: Reason field explains decision (quota_critical, high_complexity, etc)
  - test_task_external_ai_used_updated: Task.external_ai_used updated after fallback
  - test_audit_queryable: Can query FallbackDecision by task_id, decision, reason

**Test Fixtures**
  - mock_litellm_client_success: Mock LiteLLMClient with successful responses
  - mock_litellm_client_claude_fails: Mock LiteLLM where Claude times out
  - mock_litellm_client_both_fail: Mock LiteLLM where both fail
  - high_quota_state: Quota=80% remaining
  - low_quota_state: Quota=15% remaining
  - simple_plan: WorkPlan with complexity_level="simple"
  - complex_plan: WorkPlan with complexity_level="complex"
  - fallback_service: ExternalAIFallback instance

Use pytest fixtures, pytest.mark.asyncio, unittest.mock for LLM mocking.
Test coverage: >90% of ExternalAIFallback methods.
  </action>
  <verify>
Run: `pytest tests/test_fallback_integration.py -v --asyncio-mode=auto`

All tests pass (25+ test cases). Coverage report: `pytest tests/test_fallback_integration.py --cov=src/orchestrator/fallback --cov-report=term-missing`

Verify:
  - test_simple_plan_no_fallback passes
  - test_complex_plan_triggers_claude passes
  - test_low_quota_triggers_claude passes
  - test_claude_timeout_falls_back passes
  - test_ollama_failure_raises passes
  - test_both_claude_and_ollama_fail passes
  - test_fallback_decision_recorded passes
  - All quota tracking tests pass

Verify audit logging: `psql chiffon -c "SELECT * FROM fallback_decisions LIMIT 5"` (or appropriate table) shows decision history.
  </verify>
  <done>
Comprehensive test suite for ExternalAIFallback with 25+ test cases covering fallback triggers, quota tracking, Claude/Ollama failures, complexity assessment, and audit logging. All tests passing. Coverage >90%. Fallback decisions properly logged.
  </done>
</task>

</tasks>

<verification>
**Goal-backward check:**

1. ✓ Quota checking before complex tasks (should_use_external_ai method)
2. ✓ Complexity assessment determines local vs external (complexity_level check)
3. ✓ Claude fallback on quota <20% or complexity=complex (quota_threshold + complexity logic)
4. ✓ Ollama fallback if Claude fails (three-tier fallback implementation)
5. ✓ All usage logged in audit trail (FallbackDecision table)

**Must-haves validation:**
- ✓ Quota check <20% triggers Claude
- ✓ Complex tasks trigger Claude
- ✓ Quota unavailable defaults to safe Ollama
- ✓ Claude timeout/error falls back to Ollama
- ✓ Both failures raise exception
- ✓ All decisions logged for post-mortem

**Integration points:**
- ✓ Takes WorkPlan from Plan 03-02
- ✓ Uses LiteLLMClient from Phase 1
- ✓ Logs to Task.external_ai_used for Phase 5
</verification>

<success_criteria>
- [ ] FallbackDecision model added to models.py
- [ ] ExternalAIFallback class implemented in src/orchestrator/fallback.py
- [ ] Quota checking via LiteLLM.get_user_quota() working
- [ ] Complexity assessment triggers Claude for "complex" tasks
- [ ] Three-tier fallback implemented (Claude → Ollama → exception)
- [ ] All fallback decisions logged to database
- [ ] All 25+ tests passing
- [ ] Coverage >90% for ExternalAIFallback
- [ ] Error messages helpful and logged appropriately
- [ ] Quota checks gracefully handle LiteLLM unavailability
- [ ] Configuration options for quota threshold (QUOTA_THRESHOLD_PERCENT)
</success_criteria>

<output>
After completion, create `.planning/phases/03-orchestrator-core/03-04-SUMMARY.md` documenting:
- Fallback decision logic and quota thresholds
- ExternalAIFallback implementation details
- Three-tier fallback mechanism (Claude → Ollama → exception)
- Test results and coverage
- Example fallback decisions for simple/complex requests
- Cost tracking and quota management
- Integration points for Plan 03-05 (Service Integration)
</output>
