---
phase: 06
plan: 04
subsystem: infrastructure-agent
tags: [ansible-lint, playbook-analysis, suggestions, error-handling, testing]
requires: [06-01-foundation, 06-03-executor]
provides: [playbook-analyzer-service, suggestion-persistence, failure-analysis]
affects: [06-06-e2e-tests]
tech-stack:
  added: []
  patterns: [subprocess-mocking, test-driven-integration]
key-files:
  created:
    - src/agents/infra_agent/analyzer.py
    - tests/test_playbook_analyzer.py
  modified:
    - src/agents/infra_agent/agent.py
    - src/common/protocol.py
    - src/common/models.py
    - migrations/versions/007_playbook_suggestions.py
decisions:
  - id: d-06-04-01
    summary: Use ansible-lint subprocess with JSON output for analysis
    rationale: Leverages mature linting tool instead of reimplementing rules
    alternatives: [custom-yaml-parser, ansible-validate-api]
  - id: d-06-04-02
    summary: Categorize rules into 5 categories (idempotency, error_handling, performance, best_practices, standards)
    rationale: Groups findings by actionability for better prioritization
    alternatives: [severity-only, uncategorized-list]
  - id: d-06-04-03
    summary: Truncate large results (>100 findings → 50)
    rationale: Prevents overwhelming users and reduces storage requirements
    alternatives: [pagination, unlimited-storage]
  - id: d-06-04-04
    summary: Run analyzer only on playbook failure, not success
    rationale: Focuses analysis efforts on actionable failures
    alternatives: [always-analyze, manual-trigger-only]
  - id: d-06-04-05
    summary: Add analysis_result field to WorkResult protocol
    rationale: Enables structured analysis data in orchestrator responses
    alternatives: [separate-message-type, embedded-in-output-string]
metrics:
  duration: 8min
  completed: 2026-01-22
---

# Phase 06 Plan 04: Improvement Suggestions Summary

**One-liner:** ansible-lint integration with 5-category rule mapping and automatic failure analysis

## What Was Built

### PlaybookAnalyzer Service
Created complete playbook analysis service in `src/agents/infra_agent/analyzer.py`:
- **Pydantic models**: Suggestion (category, rule_id, message, reasoning, line_number, severity), AnalysisResult (playbook_path, total_issues, suggestions, by_category, analyzed_at)
- **PlaybookAnalyzer class**:
  - `async analyze_playbook()`: Main analysis entry point
  - `_run_ansible_lint()`: Subprocess execution with JSON output
  - `_categorize_rule()`: Maps ansible-lint rules to 5 categories
  - `_generate_reasoning()`: Template-based human-readable explanations
  - `_map_severity()`: Normalizes severity (error, warning, info)
  - `async _persist_suggestions()`: Bulk inserts to database

### Rule Categorization
Implemented 5-category taxonomy with 20+ rule mappings:
- **Idempotency**: no-changed-when, command-instead-of-module, risky-shell-pipe, no-free-form, risky-file-permissions
- **Error handling**: ignore-errors, no-handler, fqcn, fqcn-builtins, no-relative-paths
- **Performance**: package-latest, literal-compare, no-jinja-when, deprecated-command-syntax
- **Best practices**: yaml, name, syntax-check, jinja, key-order, no-tabs, args, var-naming, schema
- **Standards**: Everything else (default category)

### Reasoning Templates
Added 15 reasoning templates for common rules:
- Idempotency explanations (changed_when, module usage)
- Error handling guidance (ignore_errors, handlers)
- Performance tips (package versions, Jinja2 when clauses)
- Best practices (YAML syntax, task naming)

### Database Integration
- **Migration 007**: playbook_suggestions table with indexes on playbook_path, category, status
- **PlaybookSuggestion ORM model**: Validates category/severity/status choices, includes task_id FK
- **Persistence**: Optional SQLAlchemy session for suggestion storage

### InfraAgent Integration
Updated `src/agents/infra_agent/agent.py`:
- **Analyzer initialization**: Creates PlaybookAnalyzer with db_session in __init__
- **Work type handler**: analyze_playbook returns AnalysisResult as JSON
- **Failure integration**: Updated `_summary_to_result()` to async, runs analyzer on status="failed"
- **Output enhancement**: Includes suggestion count and category breakdown in failure messages
- **Analysis result field**: Added to WorkResult protocol for structured data

### Comprehensive Testing
Created `tests/test_playbook_analyzer.py` with 49 test cases:
- **Suggestion model validation** (2 tests): Valid creation, optional fields
- **AnalysisResult validation** (2 tests): Valid result, empty result
- **Rule categorization** (5 tests): All 5 categories verified
- **Reasoning generation** (2 tests): Template coverage, default fallback
- **Severity mapping** (3 tests): Error, warning, info normalization
- **ansible-lint execution mocked** (5 tests): Success, no issues, parse error, not found, timeout
- **Analyzer integration** (6 tests): Full workflow, file not found, missing ansible-lint, truncation
- **Database persistence** (6 tests): With session, without session
- **InfraAgent integration** (18 tests): analyze_playbook work type, run_playbook failure analysis, deploy_service failure analysis

All tests pass (49/49). CI-friendly with subprocess mocking.

## Deviations from Plan

### Auto-fixed Issues

**[Rule 1 - Bug] Error messages in output field instead of error_message**
- **Found during:** Task 3 (test failures)
- **Issue:** InfraAgent handlers returned error messages in output field, violating WorkResult validator requirement (error_message required when status="failed")
- **Fix:** Updated all failure returns to use error_message field with empty output
- **Files modified:** src/agents/infra_agent/agent.py
- **Commit:** 318ded1

**[Rule 3 - Blocking] Missing analysis_result field in WorkResult**
- **Found during:** Task 3 (integration implementation)
- **Issue:** WorkResult protocol model didn't have field for analysis results, blocking structured data return
- **Fix:** Added `analysis_result: Optional[dict[str, Any]]` field to WorkResult
- **Files modified:** src/common/protocol.py
- **Commit:** 5dadd53

## Success Criteria Met

- [x] PlaybookAnalyzer runs ansible-lint programmatically with JSON output
- [x] Suggestions categorized: idempotency, error_handling, performance, best_practices, standards
- [x] Reasoning provided for each suggestion (15 common rules + generic fallback)
- [x] Analysis triggered only after playbook failure (not on success)
- [x] Suggestions stored in database with playbook path, category, and timestamp
- [x] InfraAgent execute_work includes analysis in failure response
- [x] All tests pass (49 test cases)
- [x] CI-friendly: tests mock subprocess (no real ansible-lint required)

## Technical Implementation Details

### Subprocess Execution
- **Command**: `ansible-lint --format json --nocolor {playbook_path}`
- **Timeout**: 60 seconds
- **Return code handling**:
  - 0 = no issues (clean playbook)
  - 2 = issues found (expected for analysis)
  - >2 = command failure (log error, return empty list)
- **Error handling**: FileNotFoundError → raise RuntimeError("ansible-lint not installed"), TimeoutExpired → log warning, return empty list

### Truncation Logic
Large result sets (>100 findings) truncated to first 50:
- Prevents database bloat
- Reduces orchestrator memory usage
- Focuses on most critical issues (ansible-lint typically sorts by severity)

### Integration Flow
1. PlaybookExecutor runs playbook → ExecutionSummary
2. `_summary_to_result()` checks: `if status == "failed" and playbook_path`
3. Calls `analyzer.analyze_playbook()` → AnalysisResult
4. Appends summary to output: "Analysis: {total_issues} improvement suggestions"
5. Includes analysis_result in WorkResult for orchestrator
6. Logs suggestion count at INFO level

## Next Phase Readiness

**Ready for:**
- **06-06 E2E Tests**: Analyzer can be triggered in integration tests
- **Future post-mortem agent**: Suggestions table populated for learning

**Blockers/Concerns:**
- None - analyzer is fully integrated and tested

## Testing Verification

Run verification commands:
```bash
# Run migration
poetry run alembic upgrade head

# Run tests
poetry run pytest tests/test_playbook_analyzer.py -v

# Verify imports
poetry run python -c "from src.agents.infra_agent.analyzer import PlaybookAnalyzer, AnalysisResult; print('Import OK')"
```

Expected results:
- Migration 007 applies cleanly
- 49/49 tests pass
- Import succeeds without errors

## Commits

- `060846b`: feat(06-04): create PlaybookAnalyzer service with ansible-lint integration
- `5dadd53`: feat(06-04): integrate PlaybookAnalyzer into InfraAgent
- `318ded1`: test(06-04): add comprehensive PlaybookAnalyzer tests and fix integration

**Total commits:** 3 (atomic per task)
**Duration:** ~8 minutes
