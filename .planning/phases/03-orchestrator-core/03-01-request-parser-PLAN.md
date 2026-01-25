---
phase: 03-orchestrator-core
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/orchestrator/nlu.py
  - src/common/models.py
  - tests/test_request_parser.py
autonomous: true
must_haves:
  truths:
    - "User submits natural language request, orchestrator assigns request_id and parses intent"
    - "Complex requests automatically decomposed into 2-5 subtasks with confidence scoring"
    - "Ambiguous requests flagged for user clarification before planning"
    - "Out-of-scope requests logged for feature gap analysis"
    - "RequestDecomposer can parse diverse request formats (templates, free-form, parameters)"
  artifacts:
    - path: "src/orchestrator/nlu.py"
      provides: "RequestDecomposer class with decompose() and complexity assessment"
      exports: ["RequestDecomposer", "DecomposedRequest", "RequestParser"]
    - path: "src/common/models.py"
      provides: "DecomposedRequest Pydantic model with subtasks, ambiguities, out_of_scope"
      contains: "class DecomposedRequest"
  key_links:
    - from: "RequestDecomposer"
      to: "LiteLLMClient"
      via: "async def decompose() calls llm.call_llm()"
      pattern: "await self.llm.call_llm.*claude.*decompos"
    - from: "RequestDecomposer"
      to: "src/common/models.py"
      via: "returns DecomposedRequest with validated subtasks"
      pattern: "DecomposedRequest\\(.*subtasks"
---

<objective>
Build the natural language understanding (NLU) layer that accepts user requests and structures them into decomposed subtasks.

Purpose: Enable users to submit requests in natural language ("Deploy Kuma and configure portals") and have the orchestrator automatically break them down into executable subtasks with confidence scoring, ambiguity detection, and out-of-scope flagging.

Output: RequestDecomposer service with tests validating request parsing, decomposition, ambiguity handling, and out-of-scope detection.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/03-orchestrator-core/03-CONTEXT.md
@.planning/phases/03-orchestrator-core/03-RESEARCH.md

@src/common/litellm_client.py
@src/common/config.py
@src/orchestrator/service.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add DecomposedRequest Pydantic Models to src/common/models.py</name>
  <files>src/common/models.py</files>
  <action>
Add three Pydantic models to src/common/models.py (after existing Task and ExecutionLog models):

1. **Subtask** - Represents a single decomposed task:
   - order: int (task sequence, 1-based)
   - name: str (human-readable task name)
   - intent: str (recognized work type like "deploy_kuma", "add_config")
   - confidence: float (0.0-1.0 confidence in this decomposition)
   - parameters: dict (optional task-specific parameters)

2. **DecomposedRequest** - Result of request decomposition:
   - request_id: UUID (assigned by orchestrator)
   - original_request: str (full user input)
   - subtasks: list[Subtask] (decomposed tasks)
   - ambiguities: list[str] (unclear aspects, empty if none)
   - out_of_scope: list[str] (things orchestrator can't do)
   - complexity_level: str ("simple"|"medium"|"complex")
   - decomposer_model: str (which LLM decomposed this: "claude"|"ollama")

3. **RequestParsingConfig** - Configuration for NLU behavior:
   - min_confidence_threshold: float = 0.60 (below this, task is flagged as ambiguous)
   - max_subtasks: int = 10 (max subtasks per request)
   - use_claude_for_complex: bool = True (use Claude for complex requests vs Ollama)
   - log_out_of_scope: bool = True (log out-of-scope requests to DB)

Use Pydantic BaseModel, add helpful docstrings, configure Field defaults appropriately.
  </action>
  <verify>
Run `python -c "from src.common.models import Subtask, DecomposedRequest, RequestParsingConfig; print('Models imported successfully')"`.

Verify models have correct fields: `python -c "from src.common.models import DecomposedRequest; dr = DecomposedRequest(request_id='00000000-0000-0000-0000-000000000000', original_request='test', subtasks=[], ambiguities=[], out_of_scope=[], complexity_level='simple', decomposer_model='claude'); print(dr.model_dump())"`.
  </verify>
  <done>
All three Pydantic models added to models.py with proper validation. DecomposedRequest can be instantiated and serialized. Models appear in models.py after ExecutionLog.
  </done>
</task>

<task type="auto">
  <name>Task 2: Implement RequestDecomposer in src/orchestrator/nlu.py</name>
  <files>src/orchestrator/nlu.py</files>
  <action>
Create src/orchestrator/nlu.py with RequestDecomposer class implementing request parsing and decomposition.

**Class: RequestDecomposer**

Constructor:
  - llm_client: LiteLLMClient (from common.litellm_client)
  - config: RequestParsingConfig (from common.models)
  - logger: logging.Logger

Main method: `async def decompose(request: str) -> DecomposedRequest`
  1. Generate request_id (UUID4)
  2. Build decomposition prompt including:
     - User request text
     - Known agent types (infra, code, research, desktop)
     - Example decompositions showing good format
     - Instruction to return JSON with: {subtasks: [...], ambiguities: [...], out_of_scope: [...]}
  3. Call llm.call_llm() with:
     - model: "claude-opus-4.5" (Claude, not Ollama - more accurate decomposition)
     - temperature: 0.2 (low for deterministic output)
     - max_tokens: 1000
  4. Parse response JSON, validate using DecomposedRequest
  5. Assess complexity: return "complex" if any subtask.intent in ["research", "code_gen"], else "simple"
  6. Return DecomposedRequest with decomposer_model="claude"

Helper: `def _build_decomposition_prompt(request: str) -> str`
  - Returns structured prompt with system context, request, known intents, example outputs
  - Example output in prompt shows: {"subtasks": [{"order": 1, "name": "Deploy Kuma", "intent": "deploy_kuma", "confidence": 0.95}], "ambiguities": [], "out_of_scope": []}

Helper: `def _assess_complexity(subtasks: list[Subtask]) -> str`
  - Check if any subtask has complex intent (research, code_gen, architecture_review)
  - If >3 subtasks, mark as medium
  - Otherwise simple
  - Return "simple"|"medium"|"complex"

Error handling:
  - If JSON parse fails: log error, raise ValueError("Failed to parse decomposition response")
  - If request empty/None: raise ValueError("Request cannot be empty")
  - If subtasks empty after decomposition: log warning, return empty plan

Logging:
  - Info log on successful decomposition: f"Decomposed request {request_id} into {len(subtasks)} subtasks"
  - Warning on ambiguities: f"Request {request_id} has {len(ambiguities)} ambiguities"
  - Warning on out-of-scope: f"Request {request_id} has {len(out_of_scope)} out-of-scope items"
  </action>
  <verify>
Test import: `python -c "from src.orchestrator.nlu import RequestDecomposer; print('RequestDecomposer imported')"`.

Test decomposition (manual async test):
```python
import asyncio
from src.orchestrator.nlu import RequestDecomposer
from src.common.models import RequestParsingConfig
from src.common.litellm_client import LiteLLMClient

async def test():
    llm = LiteLLMClient(...)
    config = RequestParsingConfig()
    decomposer = RequestDecomposer(llm, config)
    result = await decomposer.decompose("Deploy Kuma and add portals to config")
    assert result.request_id
    assert len(result.subtasks) >= 1
    assert result.complexity_level in ["simple", "medium", "complex"]
    print("Decomposition successful:", result.model_dump())

asyncio.run(test())
```

Should produce DecomposedRequest with subtasks, ambiguities list, out_of_scope list, complexity_level.
  </verify>
  <done>
RequestDecomposer class implemented with async decompose() method. Takes natural language request, calls Claude via LiteLLM, parses JSON response into DecomposedRequest. Complexity assessment working. Error handling in place. Logging shows decision points.
  </done>
</task>

<task type="auto">
  <name>Task 3: Create comprehensive tests for request parser (src/tests/test_request_parser.py)</name>
  <files>tests/test_request_parser.py</files>
  <action>
Create tests/test_request_parser.py with pytest test cases covering request parsing and decomposition.

**Test Class 1: TestRequestDecomposition** (async tests using pytest-asyncio)
  - test_decompose_simple_request: "Deploy Kuma" → 1 subtask, simple complexity
  - test_decompose_complex_request: "Deploy Kuma and add portals and research alternatives" → 3 subtasks, at least simple/medium
  - test_decompose_with_ambiguities: Vague request like "Set up something" → has ambiguities list
  - test_decompose_with_out_of_scope: Request for unknown agent like "Write PhD thesis" → out_of_scope list populated
  - test_confidence_scoring: Each subtask has confidence 0.0-1.0
  - test_subtask_parameters: Subtasks can have optional parameters dict

**Test Class 2: TestComplexityAssessment**
  - test_simple_complexity: 1-2 simple subtasks → "simple"
  - test_medium_complexity: 3+ subtasks → "medium"
  - test_complex_complexity: Any subtask with "research" or "code_gen" intent → "complex"

**Test Class 3: TestAmbiguityDetection**
  - test_vague_request_flagged: Request without clear intent has ambiguities
  - test_clear_request_no_ambiguities: "Deploy Kuma" → empty ambiguities
  - test_conflicting_parameters: "Deploy Kuma on staging and production" → ambiguity about environment

**Test Class 4: TestOutOfScopeDetection**
  - test_unknown_agent_type: Request for unknown agent marked out_of_scope
  - test_known_agents_in_scope: Request for infra/code agents in scope

**Test Class 5: TestErrorHandling**
  - test_empty_request: decompose("") raises ValueError
  - test_none_request: decompose(None) raises ValueError
  - test_invalid_json_from_llm: Mock LLM returning invalid JSON → ValueError with helpful message
  - test_llm_timeout: Mock LLM timeout → caught, logged, ValueError raised
  - test_llm_api_error: Mock LLM raising exception → propagates with context

**Test Fixtures**
  - mock_litellm_client: Fixture returning mock LiteLLMClient
  - decomposer: Fixture creating RequestDecomposer with mock client
  - valid_decomposition_response: Fixture with example JSON response structure

Use pytest fixtures, pytest.mark.asyncio for async tests, unittest.mock for LLM mocking.
Test coverage: >90% of RequestDecomposer methods.
  </action>
  <verify>
Run: `pytest tests/test_request_parser.py -v --asyncio-mode=auto`

All tests pass (17+ test cases). Coverage report: `pytest tests/test_request_parser.py --cov=src/orchestrator/nlu --cov-report=term-missing`

Verify:
  - test_decompose_simple_request passes
  - test_decompose_complex_request passes
  - test_ambiguity_detection passes
  - test_out_of_scope_detection passes
  - All error handling tests pass
  </verify>
  <done>
Comprehensive test suite for RequestDecomposer with 17+ test cases covering decomposition, complexity assessment, ambiguity detection, out-of-scope detection, and error scenarios. All tests passing. Coverage >90%.
  </done>
</task>

</tasks>

<verification>
**Goal-backward check:**

1. ✓ Accepts natural language requests (decompose() method)
2. ✓ Structures into subtasks (DecomposedRequest with subtasks list)
3. ✓ Confidence scoring per subtask (Subtask.confidence field)
4. ✓ Ambiguity detection (ambiguities list in DecomposedRequest)
5. ✓ Out-of-scope logging (out_of_scope list in DecomposedRequest)

**Must-haves validation:**
- ✓ User submits natural language request → request_id assigned, intent parsed
- ✓ Complex requests decomposed into subtasks with confidence
- ✓ Ambiguous requests flagged for clarification
- ✓ Out-of-scope requests logged
- ✓ RequestDecomposer handles diverse request formats

**Tests validate:**
- ✓ Decomposition works for simple and complex requests
- ✓ Ambiguities correctly identified
- ✓ Out-of-scope detection working
- ✓ Error scenarios handled gracefully
- ✓ Complexity assessment accurate
</verification>

<success_criteria>
- [ ] DecomposedRequest, Subtask, RequestParsingConfig models added to models.py
- [ ] RequestDecomposer class implemented in src/orchestrator/nlu.py with async decompose()
- [ ] Decomposition prompt engineering produces valid JSON parseable to DecomposedRequest
- [ ] Complexity assessment correctly categorizes requests
- [ ] All 17+ tests in test_request_parser.py passing
- [ ] Coverage >90% for RequestDecomposer
- [ ] Logging shows decision points (decomposition, ambiguities, out-of-scope)
- [ ] Error messages helpful and logged appropriately
</success_criteria>

<output>
After completion, create `.planning/phases/03-orchestrator-core/03-01-SUMMARY.md` documenting:
- Models added to common/models.py
- RequestDecomposer implementation details
- Test results and coverage
- Example decomposition flow with "Deploy Kuma" request
- Integration points for Plan 03-02 (WorkPlanner)
</output>
