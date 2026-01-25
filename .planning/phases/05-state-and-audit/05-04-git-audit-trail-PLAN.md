---
phase: 05-state-and-audit
plan: 04
type: execute
wave: 1
depends_on: []
files_modified:
  - src/orchestrator/git_service.py
  - src/orchestrator/service.py
  - tests/test_git_service.py
autonomous: true
gap_closure: true

must_haves:
  truths:
    - "Task outcomes committed to git immediately after completion"
    - "Git commits include task_id, plan details, dispatch info, result, and timestamp"
    - "Git audit trail survives orchestrator restart (no state in memory)"
    - "Commits are idempotent (re-committing same task doesn't duplicate entries)"
  artifacts:
    - path: "src/orchestrator/git_service.py"
      provides: "GitService for committing audit entries to git"
      exports: ["GitService.commit_task_outcome()"]
    - path: "src/orchestrator/service.py"
      provides: "Integration of GitService into task completion handler"
      exports: ["OrchestratorService.dispatch_plan()"]
    - path: "tests/test_git_service.py"
      provides: "Comprehensive tests for git commit behavior and idempotency"
      exports: ["TestGitServiceCommitAudit", "TestGitServiceIdempotency"]
  key_links:
    - from: "OrchestratorService.dispatch_plan()"
      to: "GitService.commit_task_outcome()"
      via: "Post-execution handler after task completion"
      pattern: "await git_service.commit_task_outcome"
    - from: "GitService.commit_task_outcome()"
      to: "git repository"
      via: "subprocess call to git add/commit"
      pattern: "subprocess.run.*git.*commit"
---

<objective>
**Gap Closure: Git Immutable Audit Trail**

Close the gap between Phase 5 goal ("All decisions and outcomes committed to git as immutable audit trail") and current implementation (PostgreSQL audit only).

**Purpose:** Enable v1 success criterion "Git audit trail immutable" by ensuring every task outcome is permanently committed to git with full context. Provides forensic record of execution that survives database failures or modifications.

**Output:** GitService module with post-execution git commits, integrated into orchestrator task completion handler, fully tested for idempotency and error handling.
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
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create GitService for audit trail commits</name>
  <files>src/orchestrator/git_service.py</files>
  <action>
Create src/orchestrator/git_service.py (250-350 lines) implementing GitService class:

1. Class structure:
   - __init__(repo_path: str) - Initialize with git repo path (default: project root)
   - async commit_task_outcome(task: Task) -> bool - Main commit method

2. Audit entry formatting:
   - Filename: {task_id}.json in .audit/tasks/ directory (creates if needed)
   - Content structure:
     ```json
     {
       "task_id": "uuid-string",
       "status": "success|failed|rejected|cancelled",
       "plan_id": "string",
       "plan_steps": ["step1", "step2"],
       "dispatch_info": {
         "agent_pool": "string",
         "agent_id": "string",
         "dispatch_timestamp": "ISO8601"
       },
       "execution_result": {
         "outcome": {...}, // Task.outcome JSON
         "resources_used": {...}, // Task.actual_resources JSON
         "services_touched": ["service1", "service2"],
         "start_time": "ISO8601",
         "end_time": "ISO8601"
       },
       "timestamp": "ISO8601"
     }
     ```

3. Commit method behavior:
   - Read task record from PostgreSQL (via passed Task object)
   - Check if file already exists in .audit/tasks/ (idempotency check)
   - If not exists, write audit entry JSON file
   - Stage file: git add .audit/tasks/{task_id}.json
   - Commit with message: "audit: task {task_id} {status} at {timestamp}"
   - Log success/skip with task_id
   - Return bool indicating whether new commit was created

4. Error handling:
   - If .git directory not found, log warning and return False (not in git repo)
   - If git command fails, log error with stdout/stderr and raise GitServiceError
   - If Task object missing required fields, log error and raise GitServiceError
   - Do NOT crash orchestrator on git failures (git is audit, not critical path)

5. Dependencies:
   - Use subprocess.run() for git commands (not GitPython - simpler, fewer deps)
   - Use pathlib.Path for file operations
   - Use json module for audit entry formatting
   - Use logging module (logger = logging.getLogger(__name__))

6. Testing considerations:
   - Use temporary directories for test repos
   - Mock subprocess.run for negative test cases
   - Verify both new commit and idempotent re-commit scenarios
  </action>
  <verify>
1. File exists at src/orchestrator/git_service.py with ~300 lines
2. GitService class instantiates without errors: `git_service = GitService(repo_path=".")`
3. Audit entry JSON format is valid (parse with json.loads)
4. Git commands use subprocess.run with proper capture_output=True
5. Idempotency logic present: check file exists before writing
6. Error handling includes GitServiceError exception class
7. Logging calls use logger.info/warning/error appropriately
  </verify>
  <done>
- GitService class created with commit_task_outcome() method
- Audit entry JSON format matches specification
- Idempotency check implemented (skip if file exists)
- Error handling for missing .git repo and git command failures
- Comprehensive docstrings on all methods
  </done>
</task>

<task type="auto">
  <name>Task 2: Integrate GitService into orchestrator task completion handler</name>
  <files>src/orchestrator/service.py</files>
  <action>
Modify src/orchestrator/service.py to integrate GitService into task completion workflow:

1. Add GitService initialization:
   - Import GitService from orchestrator.git_service
   - In OrchestratorService.__init__(), create self.git_service = GitService(repo_path)
   - Add repo_path parameter to OrchestratorService with default "." (project root)

2. Locate task completion point:
   - Find where Task records are updated with final status (completed, failed, rejected)
   - This is likely in dispatch_plan() or a separate task_completed() method
   - Look for lines that set task.status to "completed" or similar

3. Add git commit after status update:
   - After task.status is finalized and session.commit() completes (PostgreSQL write done):
     ```python
     # Commit outcome to git audit trail
     try:
         await self.git_service.commit_task_outcome(task)
     except Exception as e:
         logger.error(f"Git audit commit failed for task {task.task_id}: {e}")
         # Continue execution - git failure should not block orchestrator
     ```

4. Ensure proper async/await:
   - If dispatch_plan() is async, await the git commit
   - If task completion is sync, wrap git_service call in asyncio.run() (document why)

5. Add to existing imports:
   - from orchestrator.git_service import GitService, GitServiceError

6. Configuration:
   - Add GIT_REPO_PATH environment variable support (default: ".")
   - Log configuration on startup: logger.info(f"Git audit trail enabled, repo: {self.git_service.repo_path}")

7. Testing considerations:
   - Task completion should not fail if git commit fails (add try/except)
   - Log errors but continue execution
  </action>
  <verify>
1. GitService is imported in OrchestratorService
2. GitService instance created in __init__ with repo_path
3. commit_task_outcome() called after task status finalization
4. Try/except wraps git commit call
5. Errors logged but do not crash orchestrator
6. Configuration via GIT_REPO_PATH environment variable works
7. dispatch_plan() or task completion method shows git commit call
  </verify>
  <done>
- GitService initialized in OrchestratorService.__init__()
- Post-completion git commit integrated into task completion workflow
- Error handling ensures git failures don't crash orchestrator
- Environment variable configuration added
- Logging shows git audit trail status on startup
  </done>
</task>

<task type="auto">
  <name>Task 3: Create comprehensive test suite for GitService and integration</name>
  <files>tests/test_git_service.py</files>
  <action>
Create tests/test_git_service.py (400-500 lines) with comprehensive test coverage:

1. Test organization (use pytest classes):

   TestGitServiceInitialization:
   - Test init with valid repo path
   - Test init with missing .git directory (should not crash)
   - Test init with invalid path

   TestAuditEntryFormatting:
   - Test audit JSON structure matches spec
   - Test all required fields present in audit entry
   - Test ISO8601 timestamp formatting
   - Test services_touched array serialization
   - Test outcome JSONB serialization

   TestCommitAuditEntry:
   - Test new commit creates file in .audit/tasks/{task_id}.json
   - Test new commit calls git add correctly
   - Test new commit calls git commit with proper message format
   - Test commit returns True on new file creation
   - Test commit includes task_id and status in git message

   TestIdempotency:
   - Test re-committing same task is idempotent (returns False, no new commit)
   - Test audit file already exists check works
   - Test multiple calls to commit_task_outcome() for same task don't create duplicate commits
   - Verify git log shows single commit not multiple

   TestErrorHandling:
   - Test graceful handling when .git directory missing
   - Test error when git command fails (mock subprocess.run to raise exception)
   - Test error when Task object missing required fields
   - Test GitServiceError exception raised on git failures
   - Test orchestrator continues execution on git errors

   TestGitCommandGeneration:
   - Test git add command uses correct path
   - Test git commit message format: "audit: task {task_id} {status} at {timestamp}"
   - Test subprocess.run called with capture_output=True, cwd set to repo_path

   TestIntegrationWithOrchestratorService:
   - Test OrchestratorService.dispatch_plan() calls git_service.commit_task_outcome()
   - Test task completion triggers git commit
   - Test failed tasks also committed to git
   - Test git commit doesn't block orchestrator on error

2. Fixture setup:
   - Use pytest tmp_path for temporary git repos
   - Initialize proper git repo with git init command in fixtures
   - Create mock Task objects with required fields
   - Mock subprocess.run for negative test cases

3. Parametrization:
   - Test multiple task statuses: success, failed, rejected, cancelled
   - Test various exception scenarios

4. Async tests:
   - Use pytest-asyncio for async test support
   - Mark async tests with @pytest.mark.asyncio
  </action>
  <verify>
1. File exists at tests/test_git_service.py with ~450 lines
2. All test classes present and runnable: pytest tests/test_git_service.py
3. Tests cover initialization, formatting, commits, idempotency, errors, integration
4. At least 30 test methods total across all test classes
5. Parametrized tests for multiple scenarios
6. Mock-based tests for error scenarios (no actual git repo failures in CI)
7. Integration tests verify OrchestratorService + GitService interaction
  </verify>
  <done>
- Comprehensive test suite created with 30+ test methods
- Coverage: initialization, audit formatting, commits, idempotency, errors, integration
- All tests passing with 100% pass rate
- Parametrized tests for multiple task statuses and error scenarios
- Integration tests verify OrchestratorService calls GitService correctly
  </done>
</task>

</tasks>

<verification>
**Functional Verification Steps:**

1. **Audit Entry Format:**
   - Create a test task, complete it, verify .audit/tasks/{task_id}.json exists
   - Parse JSON file, verify all required fields present: task_id, status, plan_id, dispatch_info, execution_result, timestamp
   - Verify ISO8601 timestamps valid (parse with datetime.fromisoformat)

2. **Git Commit Created:**
   - After task completion, run `git log --oneline .audit/tasks/`
   - Verify latest commit message: "audit: task {task_id} {status} at {timestamp}"
   - Verify commit adds exactly one file

3. **Idempotency:**
   - Complete a task (creates git commit)
   - Manually call git_service.commit_task_outcome(same_task)
   - Verify no new commit created (git log shows same single commit)
   - Verify return value is False (indicating skip)

4. **Error Handling:**
   - Test with missing .git directory
   - Verify GitService logs warning but returns False (doesn't crash)
   - Verify orchestrator continues executing other tasks

5. **Integration with Orchestrator:**
   - Execute full orchestrator request → plan → dispatch workflow
   - On task completion, verify both PostgreSQL audit AND git commit created
   - Verify orchestrator doesn't crash even if git commit fails

6. **Immutability:**
   - Verify git commits use append-only format (.audit/tasks/ directory)
   - Verify old audit entries never deleted (only new files added)
   - Verify git history shows complete execution trail
</verification>

<success_criteria>
- Phase 5 gap 1 closed: "Git audit trail immutable" is now verifiable
- GitService successfully commits task outcomes to git after completion
- Audit entries include all required context (task_id, plan, dispatch, result, timestamp)
- Commits are idempotent (re-committing same task doesn't create duplicates)
- Error handling ensures orchestrator continues if git fails (git is audit, not critical path)
- All 30+ tests passing with 100% pass rate
- Integration verified: OrchestratorService → GitService → git repository
- ROADMAP success criterion "Git audit trail immutable" satisfied for v1
</success_criteria>

<output>
After completion, create `.planning/phases/05-state-and-audit/05-04-git-audit-trail-SUMMARY.md` with:
- Duration, start/end times
- List of files created/modified
- Summary of audit entry format
- Test results: N/N passing
- Key decisions made
- Ready for Phase 5 Plan 05 (Pause/Resume Manager)
</output>
