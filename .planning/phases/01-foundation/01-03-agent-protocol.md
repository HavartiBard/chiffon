---
phase: 01-foundation
plan: 03
type: execute
wave: 2
depends_on: ["01-01"]
files_modified:
  - docs/PROTOCOL.md
  - docs/agent-protocol.yaml
  - src/common/protocol.py
  - src/common/exceptions.py
  - tests/test_protocol_contract.py
  - src/orchestrator/main.py
autonomous: true
user_setup: []

must_haves:
  truths:
    - "Agent protocol specification document exists (PROTOCOL.md)"
    - "OpenAPI specification generated (agent-protocol.yaml)"
    - "Error codes (5001-5999) defined and documented"
    - "JSON envelope format enforced (all message types conform)"
    - "Contract tests validate protocol compliance"
  artifacts:
    - path: "docs/PROTOCOL.md"
      provides: "Human-readable protocol guide with examples"
      contains: ["message types", "error codes", "timeout behavior", "retry logic", "circuit breaker"]
    - path: "docs/agent-protocol.yaml"
      provides: "OpenAPI 3.0 spec for protocol (machine-readable)"
      contains: ["components.schemas", "WorkRequest", "WorkStatus", "WorkResult", "ErrorMessage"]
    - path: "src/common/protocol.py"
      provides: "Pydantic models for protocol validation"
      exports: ["WorkRequest", "WorkStatus", "WorkResult", "ErrorMessage", "MessageEnvelope"]
    - path: "src/common/exceptions.py"
      provides: "Custom exception types mapping to error codes"
      contains: ["AgentProtocolError", "TimeoutError", "AgentUnavailableError"]
    - path: "tests/test_protocol_contract.py"
      provides: "Contract tests for protocol compliance"
      contains: ["test_message_envelope_required_fields", "test_error_codes_in_range"]
  key_links:
    - from: "src/common/protocol.py"
      to: "docs/agent-protocol.yaml"
      via: "Pydantic models match OpenAPI schemas"
      pattern: "BaseModel"
    - from: "src/common/exceptions.py"
      to: "src/common/protocol.py"
      via: "Exception types map to error codes"
      pattern: "error_code"
    - from: "tests/test_protocol_contract.py"
      to: "src/common/protocol.py"
      via: "Tests validate model schemas"
      pattern: "from src.common.protocol import"
---

## Plan: Agent Protocol Specification, OpenAPI Docs, Contract Tests

**Goal:** Define agent communication protocol with JSON envelope format, message types, error codes. Document with OpenAPI spec and markdown guide. Validate with contract tests.

**Deliverables:**
- PROTOCOL.md: Human-readable protocol guide with examples
- agent-protocol.yaml: OpenAPI 3.0 specification
- src/common/protocol.py: Pydantic models for all message types
- src/common/exceptions.py: Error codes and custom exceptions
- tests/test_protocol_contract.py: Contract tests ensuring compliance

**Success Criteria:**
- `poetry run pytest tests/test_protocol_contract.py -v` passes all protocol validation tests
- OpenAPI spec is valid YAML and can be viewed in Swagger UI
- Each message type (work_request, work_status, work_result, error) has Pydantic model
- Error codes (5001-5999) documented and mapped to exception types
- Protocol guide includes timeout, retry, circuit breaker, idempotency examples

### Tasks

<task type="auto">
  <name>Task 1: Define Pydantic models for protocol message types</name>
  <files>
    src/common/protocol.py
    src/common/exceptions.py
  </files>
  <action>
    Create type-safe protocol definitions:

    1. **src/common/exceptions.py** - Custom exception hierarchy:
       - Base: AgentProtocolError(Exception) with error_code, message, context
       - TimeoutError (5001) - Message timeout
       - AgentUnavailableError (5002) - Agent not responding
       - InvalidMessageFormatError (5003) - Malformed JSON
       - AuthenticationFailedError (5004) - Token validation failed
       - ResourceLimitExceededError (5005) - Memory/GPU limit hit
       - UnsupportedWorkTypeError (5006) - Unknown work type
       - Each exception has __init__ storing error_code, message, context dict
       - __str__ returns formatted error for logging

    2. **src/common/protocol.py** - Pydantic message definitions:
       - Import: from pydantic import BaseModel, Field, validator, UUID4
       - Define MessageEnvelope base model:
         - protocol_version: str = "1.0" (Field default)
         - message_id: UUID4 (Field default_factory=uuid4)
         - from_agent: str (Field, pattern="orchestrator|infra|desktop|code|research")
         - to_agent: str (Field, pattern="orchestrator|infra|desktop|code|research")
         - timestamp: datetime (Field default_factory=datetime.utcnow)
         - trace_id: UUID4 (Field default_factory=uuid4)
         - request_id: UUID4 (Field default_factory=uuid4)
         - type: str (Field, pattern="work_request|work_status|work_result|error")
         - payload: dict (Field, discriminated union or generic dict)
         - x_custom_fields: dict = Field(default_factory=dict)

       - Define WorkRequest model:
         - task_id: UUID4
         - work_type: str (Field, description="deploy_service|run_playbook|etc")
         - parameters: dict (work type-specific parameters)
         - hints: dict (max_duration_seconds, suggested_max_memory_mb)

       - Define WorkStatus model:
         - task_id: UUID4
         - status: str (Field, pattern="running|step_completed|paused")
         - progress_percent: int (Field ge=0, le=100)
         - step: dict with (number, name, output)

       - Define WorkResult model:
         - task_id: UUID4
         - status: str (Field, pattern="success|failed")
         - exit_code: int
         - output: str
         - resources_used: dict with (duration_seconds, gpu_vram_mb, cpu_time_ms)

       - Define ErrorMessage model:
         - error_code: int (Field ge=5001, le=5999)
         - error_message: str
         - error_context: dict nullable

       - Add Config class to each model: allow_population_by_field_name = True, use_enum_values = True

    3. Validators:
       - @validator on timestamp: ensure ISO 8601 format
       - @validator on progress_percent: ensure 0-100
       - @validator on error_code: ensure 5001-5999 range

    Models should be serializable to JSON and back (for MQ transport).
  </action>
  <verify>
    - `python -c "from src.common.protocol import MessageEnvelope, WorkRequest, WorkStatus, WorkResult, ErrorMessage; print('All models importable')"` succeeds
    - `python -c "from src.common.exceptions import AgentProtocolError, TimeoutError; print('Exceptions importable')"` succeeds
    - Create instance: `req = WorkRequest(task_id=uuid4(), work_type='deploy', parameters={}); print(req.json())` outputs valid JSON
    - Validation: Creating model with invalid error_code (-1) raises ValidationError
  </verify>
  <done>
    - Protocol message types defined with Pydantic
    - Type safety enforced (validators, field constraints)
    - Exceptions map to error codes (5001-5999)
    - Models ready for serialization to JSON
  </done>
</task>

<task type="auto">
  <name>Task 2: Write protocol documentation and OpenAPI specification</name>
  <files>
    docs/PROTOCOL.md
    docs/agent-protocol.yaml
  </files>
  <action>
    Create machine-readable and human-readable protocol specifications:

    1. **docs/PROTOCOL.md** - Protocol guide:
       - Title: "Agent Protocol Specification v1.0"
       - Overview: "JSON envelope-based message format for orchestrator ↔ agent communication"
       - Sections:

         **Message Envelope (Base)**
         - Explain: All messages wrap in envelope with protocol_version, message_id, trace_id, request_id, timestamp
         - Table: Field name, Type, Description, Required
         - Example: Full JSON envelope for work_request

         **Message Types**
         - work_request: Orchestrator → Agent, initiates work
           - Explain purpose, when sent
           - Example JSON with all fields
           - Parameters sub-section: task_id, work_type, parameters (dict), hints

         - work_status: Agent → Orchestrator, during execution
           - Explain: Sent periodically during long-running tasks
           - Example with step completion
           - Progress reporting

         - work_result: Agent → Orchestrator, final result
           - Explain: Marks task complete (success or failed)
           - Example with resources_used
           - Exit codes: 0 = success, >0 = failure

         - error: Either direction, fault signaling
           - Explain: Sent on protocol error, agent unavailable, timeout
           - Error code table: 5001-5999 definitions
           - Example error message

         **Error Codes**
         - Table: Code, Name, Meaning, Retry (yes/no), Context
         ```
         5001 | Timeout | Response not received within deadline | yes | attempted_retries, last_attempt
         5002 | Agent Unavailable | No connection to agent | yes | agent_id, last_heartbeat
         5003 | Invalid Message | Malformed JSON or missing required fields | no | validation_error
         5004 | Authentication Failed | Invalid bearer token | no | agent_id
         5005 | Resource Limit | GPU VRAM, CPU, memory exceeded | yes | limit_name, available, required
         5006 | Unsupported Work Type | Unknown work_type requested | no | work_type_requested, supported_types
         ```

         **Reliability Patterns**

         - Timeouts:
           - Default timeout: 30 seconds (orchestrator waits for agent response)
           - Per-task override in hints: max_duration_seconds
           - Circuit breaker: after 5 consecutive failures, orchestrator stops routing to agent for 60s

         - Retries:
           - Max 3 retries per message
           - Exponential backoff: 1s, 2s, 4s between attempts
           - Idempotency: request_id must match previous attempt
           - Only retry on error codes marked "yes" in table above

         - Idempotency:
           - Orchestrator sends request_id (UUID)
           - Agent checks if request_id seen before
           - If yes: return cached result (no re-execution)
           - If no: execute and cache result
           - Prevents duplicate work on network retry

         - Large Payloads:
           - If output > 1MB, split across multiple work_status messages
           - Agent chunks output in 256KB blocks
           - Orchestrator reassembles when receiving all chunks
           - Chunk sequence: step.output_chunk = "bytes 0-256k", then "bytes 256k-512k", etc.

         **Example: Full Workflow**
         - Show sequence diagram in ASCII or text:
           ```
           Orchestrator                      Agent
              |                                |
              |--- work_request (task A) ----> |
              |                           [execute]
              | <---- work_status 50% ------ |
              | <---- work_status 100% ----- |
              | <-- work_result (success) -- |
              |                                |
           ```

         **Versioning**
         - protocol_version: "1.0" in envelope
         - Agent registers supported versions on connect
         - Orchestrator negotiates lowest common version
         - Allows v2 agents to communicate with v1 orchestrator (downgrade)

         **Authentication**
         - Bearer token per agent (32-char random string)
         - Passed in Authorization header (REST) or message field (MQ)
         - Validated by orchestrator on every message
         - Token stored in config.json (not committed to git)

    2. **docs/agent-protocol.yaml** - OpenAPI 3.0 specification:
       - openapi: "3.0.0"
       - info: title, description, version 1.0
       - paths: (empty for Phase 1, added in Phase 2 when REST endpoints exist)
       - components.schemas:
         - MessageEnvelope
         - WorkRequest (including nested Parameters schema)
         - WorkStatus (including nested Step schema)
         - WorkResult (including nested ResourcesUsed schema)
         - ErrorMessage
       - Each schema:
         - type: object
         - properties: {field_name: {type, description, required, format/pattern if applicable}}
         - required: [list of required fields]
         - example: Valid JSON example for schema

       - Generate from Pydantic models if possible (using pydantic-openapi or similar)
       - Or manually write YAML ensuring consistency with protocol.py

    Ensure both documents stay in sync (update together).
  </action>
  <verify>
    - `grep -E "5001|5002|5003|timeout|circuit breaker|idempotency" docs/PROTOCOL.md` shows all key sections present
    - `python -c "import yaml; yaml.safe_load(open('docs/agent-protocol.yaml'))" ` validates YAML syntax
    - YAML contains all message type schemas: WorkRequest, WorkStatus, WorkResult, ErrorMessage
    - Example JSON in PROTOCOL.md can be parsed: `python -c "import json; json.loads('...')"`
    - Check for sync: Model fields in protocol.py match PROTOCOL.md and agent-protocol.yaml
  </verify>
  <done>
    - Protocol specification complete (PROTOCOL.md)
    - OpenAPI spec defined (agent-protocol.yaml)
    - All message types documented with examples
    - Error codes (5001-5999) explained
    - Reliability patterns (timeout, retry, idempotency, circuit breaker) detailed
  </done>
</task>

<task type="auto">
  <name>Task 3: Create contract tests to validate protocol compliance</name>
  <files>
    tests/test_protocol_contract.py
  </files>
  <action>
    Define contract tests ensuring all agents conform to protocol:

    1. **tests/test_protocol_contract.py** - Protocol validation tests:
       - Import: pytest, json, uuid, datetime
       - Import protocol models from src.common.protocol
       - Import exceptions from src.common.exceptions

       - Test: test_message_envelope_required_fields
         - Create instances of each model (WorkRequest, WorkStatus, etc.)
         - Assert all required fields present (protocol_version, message_id, trace_id, etc.)
         - Assert defaults assigned correctly

       - Test: test_work_request_valid
         - Create valid WorkRequest instance
         - Serialize to JSON
         - Deserialize back
         - Assert round-trip preserves all fields

       - Test: test_work_request_invalid_work_type
         - Try creating WorkRequest with unsupported work_type
         - Assert ValidationError raised

       - Test: test_error_codes_in_range
         - For each custom exception: assert error_code between 5001-5999

       - Test: test_error_message_serialization
         - Create ErrorMessage with all fields
         - Serialize to JSON
         - Verify JSON contains error_code, error_message, error_context

       - Test: test_progress_percent_validation
         - Create WorkStatus with progress_percent = 0, 50, 100 (valid)
         - Try progress_percent = -1, 101 (invalid)
         - Assert ValidationError on invalid

       - Test: test_timestamp_format
         - Create any message
         - Assert timestamp is ISO 8601 format

       - Test: test_uuid_fields
         - Create message, serialize to JSON
         - Verify message_id, trace_id, request_id are UUIDs (valid format)

       - Test: test_work_result_resources_used
         - Create WorkResult with resources_used
         - Assert can serialize/deserialize JSON
         - Verify types: duration_seconds (int), gpu_vram_mb (int), etc.

       - Test: test_large_output_chunking
         - Create WorkStatus with output > 1MB (mocked)
         - Verify protocol supports chunking (output_chunk field)

    - Use pytest fixtures:
      - @pytest.fixture for sample_task_id (uuid4())
      - @pytest.fixture for valid_work_request (returns WorkRequest instance)

    - Run all tests: `poetry run pytest tests/test_protocol_contract.py -v`

    Keep tests focused on contract validation (not integration with actual MQ).
  </action>
  <verify>
    - `poetry run pytest tests/test_protocol_contract.py -v` runs and all tests pass
    - `poetry run pytest tests/test_protocol_contract.py::test_message_envelope_required_fields -v` shows OK
    - `poetry run pytest tests/ --cov=src.common.protocol --cov-report=term-missing` shows >80% coverage for protocol module
    - No test failures on protocol models or exceptions
  </verify>
  <done>
    - Contract tests written and passing
    - Protocol compliance validated
    - All message types tested for serialization
    - Error codes validated (5001-5999 range)
    - Ready for Phase 2 integration with RabbitMQ
  </done>
</task>

</tasks>

<verification>
After all tasks complete:
1. `poetry run pytest tests/test_protocol_contract.py -v` — all tests pass
2. `python -c "import yaml; yaml.safe_load(open('docs/agent-protocol.yaml'))"` — valid YAML
3. `grep -c "5001\|5002\|5003\|5004\|5005\|5006" docs/PROTOCOL.md` — shows all error codes present
4. Verify docs/PROTOCOL.md contains: "message types", "timeout", "retry", "circuit breaker", "idempotency", "example workflow"
5. Verify src/common/protocol.py has all message types: WorkRequest, WorkStatus, WorkResult, ErrorMessage
6. Verify src/common/exceptions.py has exception classes mapping to error codes
</verification>

<success_criteria>
- Protocol specification complete (PROTOCOL.md with examples)
- OpenAPI specification generated (agent-protocol.yaml)
- Pydantic models enforce type safety and validation
- Error codes (5001-5999) defined and mapped to exceptions
- Contract tests validate protocol compliance
- Protocol ready for Phase 2 RabbitMQ integration
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation/01-03-SUMMARY.md` with:
- Protocol version: 1.0
- Message types defined: work_request, work_status, work_result, error
- Error codes: 5001-5999 range confirmed
- Contract tests: all passing
- Documentation: PROTOCOL.md and agent-protocol.yaml verified
</output>
