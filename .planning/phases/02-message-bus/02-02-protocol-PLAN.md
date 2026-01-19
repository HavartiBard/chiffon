---
phase: 02-message-bus
plan: 02
type: execute
wave: 1
depends_on: []
files_modified: [pyproject.toml, src/common/protocol.py, src/common/exceptions.py, tests/test_protocol.py]
autonomous: true
must_haves:
  truths:
    - "Agent protocol models validate correctly for all message types (work_request, work_result, error, status_update)"
    - "Correlation IDs (trace_id, request_id) present in all message types"
    - "Priority levels (1-5) enforced in message validation"
    - "Timestamp validation rejects malformed ISO 8601 strings"
    - "Pydantic model serialization/deserialization round-trips correctly to/from JSON"
  artifacts:
    - path: "src/common/protocol.py"
      provides: "Message envelope and type-specific payloads (already partial from Phase 1)"
      exports: ["MessageEnvelope", "WorkRequest", "WorkResult", "WorkStatus", "StatusUpdate", "ErrorMessage"]
      min_lines: 200
    - path: "src/common/exceptions.py"
      provides: "Protocol exception hierarchy"
      exports: ["ProtocolError", "ValidationError", "TimeoutError"]
    - path: "tests/test_protocol.py"
      provides: "Contract tests for protocol (40+ tests)"
      contains: "test_message_envelope_"
    - path: "pyproject.toml"
      provides: "Dependencies: aio-pika, python-json-logger"
      contains: "aio-pika"
  key_links:
    - from: "src/common/protocol.py"
      to: "pydantic v2"
      via: "BaseModel + field validators for version, types, timestamps"
    - from: "tests/test_protocol.py"
      to: "src/common/protocol.py"
      via: "pytest contract tests for all message types"
---

<objective>
Extend and complete the agent communication protocol started in Phase 1. Add missing message types (StatusUpdate, ErrorMessage), implement validation for correlation IDs, priority levels, and timestamps. Add 40+ contract tests to ensure protocol is robust before agents use it.

Purpose: Agents and orchestrator must speak the same language; protocol defines that language with strict validation
Output: Complete protocol.py with all message types; comprehensive test suite; updated pyproject.toml with aio-pika dependency
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/ROADMAP.md
@.planning/phases/02-message-bus/02-CONTEXT.md
@.planning/phases/02-message-bus/02-RESEARCH.md
@/home/james/Projects/chiffon/src/common/protocol.py
@/home/james/Projects/chiffon/src/common/exceptions.py
@/home/james/Projects/chiffon/pyproject.toml
</context>

<tasks>

<task type="auto">
  <name>Task 1: Update pyproject.toml with aio-pika and python-json-logger dependencies</name>
  <files>pyproject.toml</files>
  <action>
Add to [tool.poetry.dependencies] section:
- aio-pika = "^13.0"  # Async AMQP client for RabbitMQ
- python-json-logger = "^2.0"  # Structured JSON logging with correlation IDs

Add to [tool.poetry.group.dev.dependencies] section:
- pytest-aio = "^0.3"  # Async test support for aio-pika consumers

Remove pika = "^1.3.0" from dependencies (replaced by aio-pika).

Keep all existing dependencies (fastapi, sqlalchemy, pydantic, etc.).

Rationale (from RESEARCH.md): aio-pika is async-native and works seamlessly with FastAPI's event loop. Pika is synchronous and requires pooling complexity. python-json-logger enables structured logging with trace_id propagation.
  </action>
  <verify>
1. Syntax: poetry check (should show no errors)
2. Dependencies listed: grep -E "aio-pika|python-json-logger" pyproject.toml
3. Pika removed: grep -c "^pika" pyproject.toml should be 0
4. Can install: poetry lock && poetry install (don't actually run, but verify lock file would succeed)
  </verify>
  <done>
pyproject.toml updated with aio-pika ^13.0, python-json-logger ^2.0, and pytest-aio ^0.3. Pika removed.
  </done>
</task>

<task type="auto">
  <name>Task 2: Complete src/common/protocol.py with all message types and validation</name>
  <files>src/common/protocol.py</files>
  <action>
Extend existing protocol.py (Phase 1 has MessageEnvelope, WorkRequest, Step, WorkStatus) with:

1. Complete existing message types:
   - WorkRequest (already exists, verify has: task_id, work_type, parameters, hints with deadline_seconds and estimated_duration_seconds)
   - WorkStatus (already exists as work status updates during execution)

2. Add StatusUpdate message (agent heartbeat):
   ```
   class StatusUpdate(BaseModel):
       agent_id: UUID = Field(description="Unique agent identifier")
       agent_type: str = Field(pattern="^(orchestrator|infra|desktop|code|research)$")
       status: str = Field(pattern="^(online|offline|busy)$")
       current_task_id: Optional[UUID] = Field(default=None, description="Task currently being processed")
       resources: dict = Field(
           default_factory=dict,
           description="Resource metrics: {cpu_percent, memory_percent, gpu_vram_available_gb, gpu_vram_total_gb}"
       )
       timestamp: datetime = Field(default_factory=datetime.utcnow)
   ```

3. Add WorkResult message (final result of work):
   ```
   class WorkResult(BaseModel):
       task_id: UUID = Field(description="Task being reported on")
       status: str = Field(pattern="^(completed|failed|cancelled)$")
       exit_code: int = Field(description="Process exit code (0 = success)")
       output: str = Field(default="", description="Work output/stdout")
       error_message: Optional[str] = Field(default=None, description="Error if status=failed")
       duration_ms: int = Field(description="Total work duration in milliseconds")
       agent_id: UUID = Field(description="Agent that executed the work")
       resources_used: dict = Field(
           default_factory=dict,
           description="Resource consumption: {cpu_time_ms, memory_peak_mb, gpu_memory_used_mb}"
       )
   ```

4. Add ErrorMessage for protocol errors:
   ```
   class ErrorMessage(BaseModel):
       error_code: int = Field(ge=1000, le=9999, description="Numeric error code")
       error_message: str = Field(description="Human-readable error description")
       context: dict = Field(
           default_factory=dict,
           description="Additional debugging context (original_message_id, affected_queue, etc)"
       )
   ```

5. Add priority field to MessageEnvelope:
   - priority: int = Field(default=3, ge=1, le=5, description="Priority level 1-5 for RabbitMQ queue")

6. Add validators:
   - For StatusUpdate: validate that resources dict has expected keys (cpu_percent, gpu_vram_available_gb, etc.)
   - For WorkResult: validate that if status='failed', error_message is not None
   - For ErrorMessage: validate error_code is in expected ranges (e.g., 1000-1999 for protocol errors, 2000-2999 for agent errors, 3000-3999 for orchestrator errors)

7. Extend MessageEnvelope.payload validation:
   - payload must not be empty dict (at minimum, should contain relevant fields for the message type)
   - Consider strict mode to prevent typos in payload keys

8. Add to_json() and from_json() class methods for MessageEnvelope:
   - to_json() -> str: serialize to JSON string with ISO 8601 timestamps
   - from_json(json_str: str) -> MessageEnvelope: deserialize from JSON with validation

Ensure all models have ConfigDict with:
- validate_by_name=True
- use_enum_values=True
- arbitrary_types_allowed=False (strict type checking)

Follow existing Phase 1 patterns in protocol.py.
  </action>
  <verify>
1. Syntax: python -m py_compile src/common/protocol.py
2. Type check: mypy src/common/protocol.py --strict
3. Import test: python -c "from src.common.protocol import StatusUpdate, WorkResult, ErrorMessage, MessageEnvelope; print('✓ All models import')"
4. Instantiation test (run in Python REPL or script):
   - Create StatusUpdate with agent_id, agent_type, status, resources
   - Create WorkResult with task_id, status, exit_code, duration_ms, agent_id
   - Create ErrorMessage with error_code, error_message
   - All should serialize to JSON without errors
5. Validation test:
   - Try creating WorkResult with status='failed' but error_message=None -> should fail
   - Try creating StatusUpdate with status='invalid' -> should fail
   - Try creating ErrorMessage with error_code=500 (not in valid range) -> should fail
  </verify>
  <done>
src/common/protocol.py extended with StatusUpdate, WorkResult, ErrorMessage. All message types validate correctly. Pydantic validators enforce constraints (priority 1-5, error_codes in ranges, failed results must have error_message).
  </done>
</task>

<task type="auto">
  <name>Task 3: Create comprehensive protocol contract tests (tests/test_protocol.py)</name>
  <files>tests/test_protocol.py</files>
  <action>
Create tests/test_protocol.py with 40+ test functions covering:

1. MessageEnvelope validation (10 tests):
   - test_message_envelope_requires_from_agent
   - test_message_envelope_requires_to_agent
   - test_message_envelope_requires_type
   - test_message_envelope_validates_agent_type_values (only: orchestrator, infra, desktop, code, research)
   - test_message_envelope_validates_message_type_values (only: work_request, work_status, work_result, error)
   - test_message_envelope_generates_unique_message_id
   - test_message_envelope_generates_unique_trace_id
   - test_message_envelope_timestamp_defaults_to_utcnow
   - test_message_envelope_priority_must_be_1_to_5
   - test_message_envelope_to_json_and_from_json_round_trip

2. WorkRequest validation (5 tests):
   - test_work_request_requires_task_id
   - test_work_request_requires_work_type
   - test_work_request_accepts_optional_parameters
   - test_work_request_accepts_optional_hints
   - test_work_request_serializes_to_json

3. WorkResult validation (6 tests):
   - test_work_result_requires_task_id
   - test_work_result_requires_status
   - test_work_result_requires_exit_code
   - test_work_result_requires_duration_ms
   - test_work_result_requires_agent_id
   - test_work_result_failed_must_have_error_message
   - test_work_result_completed_can_omit_error_message

4. StatusUpdate validation (5 tests):
   - test_status_update_requires_agent_id
   - test_status_update_requires_agent_type
   - test_status_update_requires_status_field
   - test_status_update_validates_status_values (online, offline, busy)
   - test_status_update_includes_resource_metrics

5. ErrorMessage validation (4 tests):
   - test_error_message_requires_error_code
   - test_error_message_requires_error_message_field
   - test_error_message_error_code_must_be_1000_to_9999
   - test_error_message_accepts_optional_context

6. Correlation ID tests (5 tests):
   - test_trace_id_propagates_in_round_trip
   - test_request_id_propagates_in_round_trip
   - test_trace_id_can_be_set_explicitly
   - test_request_id_can_be_set_explicitly
   - test_multiple_messages_have_different_trace_ids

7. Timestamp tests (3 tests):
   - test_timestamp_parses_iso_8601_string
   - test_timestamp_parses_iso_8601_string_with_z_suffix
   - test_timestamp_rejects_invalid_format

8. Error condition tests (3 tests):
   - test_message_with_invalid_json_fails_to_deserialize
   - test_message_with_missing_required_field_fails
   - test_message_with_type_mismatch_fails

Use pytest fixtures for:
- @pytest.fixture valid_message_envelope() -> returns valid MessageEnvelope
- @pytest.fixture valid_work_request() -> returns valid WorkRequest
- etc.

Use parametrize for testing multiple valid values:
- @pytest.mark.parametrize("agent_type", ["orchestrator", "infra", "desktop", "code", "research"])
- def test_accepts_all_valid_agent_types(agent_type): ...

All tests should use asyncio_mode="auto" (already configured in pyproject.toml).

Run all tests in isolation (no shared state between tests).

Expected test file size: ~400-500 lines of code.
  </action>
  <verify>
1. Syntax: python -m py_compile tests/test_protocol.py
2. Count tests: grep -c "^def test_" tests/test_protocol.py should be >= 40
3. Run tests: pytest tests/test_protocol.py -v
   - Expected: All tests PASS
   - If any fail, fix the protocol.py implementation
4. Coverage: pytest tests/test_protocol.py --cov=src.common.protocol --cov-report=term-missing
   - Expected: >=85% coverage of protocol.py
  </verify>
  <done>
tests/test_protocol.py created with 40+ contract tests. All tests pass. Coverage >=85% of src/common/protocol.py.
  </done>
</task>

</tasks>

<verification>
After execution:
1. Import test: python -c "from src.common.protocol import MessageEnvelope, WorkRequest, WorkResult, StatusUpdate, ErrorMessage; print('✓')"
2. Dependency check: poetry lock (should complete without errors)
3. Full test run: pytest tests/test_protocol.py -v
4. Type check: mypy src/common/protocol.py --strict (should show 0 errors)
5. Linting: ruff check src/common/protocol.py tests/test_protocol.py
</verification>

<success_criteria>
- pyproject.toml updated: aio-pika ^13.0 and python-json-logger ^2.0 present; pika removed
- src/common/protocol.py: All 6 message types (MessageEnvelope, WorkRequest, WorkResult, StatusUpdate, ErrorMessage, WorkStatus) complete and validated
- tests/test_protocol.py: 40+ tests, all passing
- No import errors, no type errors
- All message types serialize/deserialize correctly to/from JSON
- Priority levels (1-5) enforced in all messages
- Correlation IDs (trace_id, request_id) present in all messages
- Timestamp validation accepts ISO 8601 with and without Z suffix
</success_criteria>

<output>
After completion, create `.planning/phases/02-message-bus/02-02-SUMMARY.md` with:
- Message types completed (list all 6)
- Test coverage (e.g., 42 tests, 87% coverage)
- Dependency changes (aio-pika ^13.0, python-json-logger ^2.0)
- Next step reference: "Proceed to 02-03-agent-framework-PLAN.md (parallel with 02-04)"
</output>
