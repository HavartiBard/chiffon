---
phase: 03-orchestrator-core
plan: 07
type: gap_closure
wave: 3
depends_on: ["03-06"]
gap_closure: true
files_modified:
  - src/orchestrator/fallback.py
  - tests/test_fallback_integration.py
  - tests/test_orchestrator_e2e.py
autonomous: true
must_haves:
  truths:
    - "FallbackDecision.quota_remaining_percent uses correct fraction values (0.0-1.0, not 0-100)"
    - "All 111 fallback integration tests passing"
    - "No validation errors on FallbackDecision creation"
    - "External AI fallback requirement ORCH-05 satisfied: orchestrator falls back to Claude when quota <20%"
  artifacts:
    - path: "src/orchestrator/fallback.py"
      provides: "Fixed ExternalAIFallback with correct quota field values"
      exports: ["ExternalAIFallback"]
---

# Phase 3.07: Quota Validation Field Fix

## Objective

Gap closure (03-06) introduced a regression: FallbackDecision quota_remaining_percent field expects fraction (0.0-1.0) but gap closure multiplied by 100, causing validation failures.

This quick-fix plan corrects the quota values.

## Task: Fix quota_remaining_percent to use correct fraction values

**Current Error:**
- Model constraint: `quota_remaining_percent: float = Field(..., ge=0.0, le=1.0)`
- Code produces: `quota_remaining_percent=80.0` (percentage)
- Result: Validation error "Input should be less than or equal to 1"
- Impact: 60/111 fallback tests failing, requirement ORCH-05 blocked

**Fix:**
1. In `src/orchestrator/fallback.py`, remove the multiplication by 100 in 4 locations:
   - Line 79: `quota_remaining_percent=remaining_quota * 100` → `quota_remaining_percent=remaining_quota`
   - Line 95: Same fix
   - Line 110: Same fix
   - Line 124: Same fix

2. In `tests/test_fallback_integration.py`, fix mock fixture quota values:
   - Line ~123: `quota_remaining_percent=80.0` → `quota_remaining_percent=0.8`
   - Line ~456: `quota_remaining_percent=50.0` → `quota_remaining_percent=0.5`
   - Line ~789: `quota_remaining_percent=15.0` → `quota_remaining_percent=0.15`

3. In `tests/test_orchestrator_e2e.py`, fix mock quota values:
   - Update all mock_fallback fixture calls to use valid fractions

**Success Criteria:**
- All 111 fallback integration tests passing
- No "Input should be less than or equal to 1" validation errors
- FallbackDecision created and recorded successfully
- All 61 E2E tests still passing
- 451/451 total tests passing (339 + 111 + 61)

## Definition of Done

- [ ] quota_remaining_percent values corrected to fractions (0.0-1.0)
- [ ] All fallback tests passing (111/111)
- [ ] All E2E tests passing (61/61)
- [ ] SUMMARY.md created
- [ ] Changes committed
