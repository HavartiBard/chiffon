---
phase: 03-orchestrator-core
plan: 01
subsystem: orchestrator
tags: [NLU, request-parsing, decomposition, Claude, LiteLLM, Pydantic]

requires:
  - phase: 02-message-bus
    provides: RabbitMQ message infrastructure, LiteLLMClient wrapper, OrchestratorService base

provides:
  - RequestDecomposer service for natural language request parsing
  - DecomposedRequest, Subtask, RequestParsingConfig Pydantic models
  - Comprehensive test suite (66 test cases)
  - Intent-to-subtask decomposition with confidence scoring
  - Ambiguity and out-of-scope detection

affects:
  - 03-02: WorkPlanner (consumes DecomposedRequest, produces WorkPlan)
  - 03-03: Agent Routing (receives structured subtasks to route)
  - Phase 5+: State & Audit (tracks request decomposition decisions)

tech-stack:
  added:
    - No new dependencies (uses existing LiteLLM, Pydantic)
  patterns:
    - Async request decomposition via LLM (Claude)
    - Structured prompt engineering with examples
    - JSON response parsing with markdown code block handling
    - Complexity assessment heuristics (intents, subtask count)

key-files:
  created:
    - src/orchestrator/nlu.py (RequestDecomposer class, 228 lines)
    - tests/test_request_parser.py (66 test cases, 659 lines)
  modified:
    - src/common/models.py (added 3 Pydantic models, 119 lines, fixed datetime import)

key-decisions:
  - Claude only (not Ollama) for decomposition to ensure accuracy
  - Temperature 0.2 for deterministic structured output
  - Max 1000 tokens for decomposition (5+ subtasks rare)
  - Confidence threshold 0.60 (configurable) for ambiguity flagging
  - Complexity assessment: research/code_gen intents → complex; 3+ subtasks → medium

patterns-established:
  - Pydantic models for all LLM-facing structures (DecomposedRequest, Subtask)
  - Async methods using LiteLLMClient (no blocking I/O)
  - Structured prompt with known agent types + example outputs
  - JSON parsing resilient to markdown code blocks (```json...```)
  - Comprehensive error handling with specific ValueError messages

metrics:
  duration: 45min
  completed: 2026-01-19
---

# Phase 3 Plan 1: Request Parser Summary

**Natural language request decomposition into structured subtasks with ambiguity detection, out-of-scope flagging, and complexity assessment via Claude**

## Performance

- **Duration:** 45 min
- **Started:** 2026-01-19T14:32:00Z
- **Completed:** 2026-01-19T15:17:00Z
- **Tasks:** 3
- **Files created:** 2
- **Files modified:** 1

## Accomplishments

- **RequestDecomposer service:** Accepts natural language requests, uses Claude to parse intent and decompose into 1-5 executable subtasks with confidence scores
- **Pydantic models:** DecomposedRequest (with subtasks, ambiguities, out_of_scope, complexity assessment), Subtask (order, intent, confidence, parameters), RequestParsingConfig (min_confidence, max_subtasks, use_claude_for_complex, log_out_of_scope)
- **Comprehensive test coverage:** 66 test cases across 5 test classes covering decomposition, complexity assessment, ambiguity detection, out-of-scope detection, and error scenarios
- **Production-ready error handling:** Validates input, parses markdown-wrapped JSON, handles malformed responses gracefully with informative error messages

## Task Commits

1. **Task 1: Add DecomposedRequest Pydantic Models** - `5443ca7` (feat)
   - Added Subtask, DecomposedRequest, RequestParsingConfig models
   - Fixed missing datetime import in models.py

2. **Task 2: Implement RequestDecomposer** - `0399a17` (feat)
   - RequestDecomposer class with async decompose() method
   - Prompt engineering with known agent types and examples
   - JSON response parsing with markdown code block stripping
   - Complexity assessment heuristics
   - Comprehensive logging and error handling

3. **Task 3: Create Test Suite** - `01d33b7` (test)
   - 22 test methods × 3 async backends = 66 test cases
   - TestRequestDecomposition (simple/complex requests, parameters)
   - TestComplexityAssessment (simple/medium/complex categorization)
   - TestAmbiguityDetection (vague vs clear requests)
   - TestOutOfScopeDetection (unknown agent types)
   - TestErrorHandling (empty requests, invalid JSON, LLM errors, markdown parsing)

## Files Created/Modified

- `src/orchestrator/nlu.py` - RequestDecomposer service with async decompose(), prompt builder, complexity assessment (228 lines)
- `tests/test_request_parser.py` - Comprehensive test suite with fixtures and 5 test classes (659 lines)
- `src/common/models.py` - Added Subtask, DecomposedRequest, RequestParsingConfig Pydantic models; fixed datetime import (119 new lines)

## Decisions Made

**1. Claude-only decomposition (not Ollama)**
   - Rationale: Decomposition accuracy critical for downstream work planning. Claude's superior reasoning justifies LLM cost for this step.

**2. Low temperature (0.2) for structured output**
   - Rationale: Ensures JSON parsing consistency. Decomposition is deterministic; randomness not helpful.

**3. Max 1000 tokens per decomposition**
   - Rationale: 5+ subtasks rare for user requests. Limit prevents runaway responses.

**4. Confidence threshold 0.60**
   - Rationale: Balances false positives (over-flagging) with safety. Subtasks below 0.60 confidence trigger ambiguity review.

**5. Complexity: research/code_gen intents → complex; 3+ subtasks → medium**
   - Rationale: Heuristic captures need for external reasoning. Configurable in future via intent registry.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Fixed missing datetime import in models.py**
- **Found during:** Task 1 verification
- **Issue:** models.py imported datetime type but not datetime module; WorkPlan model (pre-existing) used datetime.utcnow() → NameError
- **Fix:** Added `from datetime import datetime` at top of models.py
- **Files modified:** src/common/models.py
- **Verification:** All imports succeed, models instantiate correctly
- **Committed in:** `5443ca7` + `0399a17` (both task commits)

**1. [Rule 2 - Missing Critical] Removed duplicate Pydantic imports in models.py**
- **Found during:** Task 1 completion
- **Issue:** Pydantic imports appeared twice (lines 8 and 298) after adding models
- **Fix:** Removed duplicate `from pydantic import BaseModel, Field` at line 298
- **Files modified:** src/common/models.py
- **Verification:** All models import cleanly
- **Committed in:** `0399a17` (included in Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 missing critical)
**Impact on plan:** Both auto-fixes necessary for correctness. No scope creep. All three planned tasks completed exactly as specified.

## Issues Encountered

None - plan executed as written after auto-fixes resolved import issues.

## User Setup Required

None - no external service configuration required. Uses existing LiteLLM and Claude API access from Phase 1.

## Next Phase Readiness

**Ready for 03-02 (WorkPlanner):**
- RequestDecomposer fully functional and tested
- DecomposedRequest output structure stable and validated
- Can now consume decomposed requests and build executable work plans
- Complexity assessment provides input for planning algorithm

**Blockers/Concerns:**
- None identified
- RequestDecomposer can be called synchronously if async not available

**Suggestions for Phase 3-02:**
- WorkPlanner should use DecomposedRequest.complexity_level to inform resource estimation heuristics
- Consider caching decomposition results if same request submitted multiple times
- Ambiguities list can drive user confirmation flow before WorkPlanner executes

---

*Phase: 03-orchestrator-core*
*Completed: 2026-01-19*
