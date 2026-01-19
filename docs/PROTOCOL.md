# Agent Protocol Specification v1.0

## Overview

The Chiffon agent protocol defines a JSON envelope-based message format for orchestrator ↔ agent communication. All messages follow the same envelope structure to ensure consistency, traceability, and reliability across the system.

**Key Principles:**
- Stateless request-response model
- Full auditability via trace IDs
- Idempotent retry with request IDs
- Extensible via custom fields
- Error codes in 5001-5999 range

---

## Message Envelope (Base)

All messages wrap in a standard envelope that provides protocol versioning, tracing, routing, and timing information.

| Field | Type | Description | Required |
|-------|------|-------------|----------|
| `protocol_version` | string | Protocol version (default "1.0") | Yes |
| `message_id` | UUID | Unique identifier for this message | Yes |
| `from_agent` | string | Sender agent type (orchestrator\|infra\|desktop\|code\|research) | Yes |
| `to_agent` | string | Recipient agent type | Yes |
| `timestamp` | datetime | ISO 8601 timestamp when sent | Yes |
| `trace_id` | UUID | Distributed trace ID for end-to-end logging | Yes |
| `request_id` | UUID | Request ID for idempotency (retry safety) | Yes |
| `type` | string | Message type (work_request\|work_status\|work_result\|error) | Yes |
| `payload` | object | Type-specific message content | Yes |
| `x_custom_fields` | object | Custom fields for extensions (optional) | No |

**Example Full Envelope (work_request):**

```json
{
  "protocol_version": "1.0",
  "message_id": "550e8400-e29b-41d4-a716-446655440001",
  "from_agent": "orchestrator",
  "to_agent": "infra",
  "timestamp": "2026-01-19T04:21:04Z",
  "trace_id": "550e8400-e29b-41d4-a716-446655440002",
  "request_id": "550e8400-e29b-41d4-a716-446655440003",
  "type": "work_request",
  "payload": {
    "task_id": "550e8400-e29b-41d4-a716-446655440004",
    "work_type": "run_playbook",
    "parameters": {
      "playbook": "deploy_kuma.yml",
      "extra_vars": {
        "version": "1.4.0"
      }
    },
    "hints": {
      "max_duration_seconds": 300,
      "max_memory_mb": 512
    }
  },
  "x_custom_fields": {}
}
```

---

## Message Types

### work_request

**Direction:** Orchestrator → Agent

**Purpose:** Initiates work on an agent. The orchestrator sends this when it wants the agent to perform a task.

**Timing:** Sent once per task. The agent processes it and responds with work_status updates, then work_result.

**Parameters:**

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | UUID | Unique identifier for this task |
| `work_type` | string | Type of work (e.g., deploy_service, run_playbook, generate_code) |
| `parameters` | object | Work type-specific parameters (structure varies by work_type) |
| `hints` | object | Scheduling hints for orchestrator (max_duration_seconds, max_memory_mb) |

**Example work_request:**

```json
{
  "type": "work_request",
  "payload": {
    "task_id": "550e8400-e29b-41d4-a716-446655440004",
    "work_type": "run_playbook",
    "parameters": {
      "playbook": "deploy_kuma.yml",
      "extra_vars": {
        "version": "1.4.0",
        "environment": "homelab"
      }
    },
    "hints": {
      "max_duration_seconds": 300,
      "max_memory_mb": 512
    }
  }
}
```

---

### work_status

**Direction:** Agent → Orchestrator

**Purpose:** Provides progress updates during long-running work. Sent periodically while the agent executes the task.

**Timing:** Sent multiple times during execution, approximately every 5-30 seconds depending on work type.

**Step Information:**

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | UUID | Which task this status is for |
| `status` | string | Current status (running\|step_completed\|paused) |
| `progress_percent` | int | Progress as percentage 0-100 |
| `step.number` | int | Step sequence number |
| `step.name` | string | Human-readable name of current step |
| `step.output` | string | Output or logs from this step |

**Example work_status (50% complete):**

```json
{
  "type": "work_status",
  "payload": {
    "task_id": "550e8400-e29b-41d4-a716-446655440004",
    "status": "running",
    "progress_percent": 50,
    "step": {
      "number": 2,
      "name": "Configure Kuma settings",
      "output": "Updating config.yaml...\nAdded uptime monitors: 3\n"
    }
  }
}
```

---

### work_result

**Direction:** Agent → Orchestrator

**Purpose:** Marks task completion with final outcome, exit code, and resource usage.

**Timing:** Sent exactly once when work completes (success or failure). Terminates the task lifecycle.

**Result Information:**

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | UUID | Which task completed |
| `status` | string | Completion status (success\|failed) |
| `exit_code` | int | Exit code (0 = success, >0 = failure) |
| `output` | string | Final output/logs from entire task |
| `resources_used.duration_seconds` | int | Total execution time in seconds |
| `resources_used.gpu_vram_mb` | int | GPU VRAM used in MB (if applicable) |
| `resources_used.cpu_time_ms` | int | CPU time used in milliseconds |

**Example work_result (success):**

```json
{
  "type": "work_result",
  "payload": {
    "task_id": "550e8400-e29b-41d4-a716-446655440004",
    "status": "success",
    "exit_code": 0,
    "output": "Deployment completed successfully.\nKuma instance running at https://kuma.homelab:3000\nMonitored services: 5",
    "resources_used": {
      "duration_seconds": 87,
      "gpu_vram_mb": 0,
      "cpu_time_ms": 12450
    }
  }
}
```

**Example work_result (failure):**

```json
{
  "type": "work_result",
  "payload": {
    "task_id": "550e8400-e29b-41d4-a716-446655440004",
    "status": "failed",
    "exit_code": 1,
    "output": "Deployment failed.\nReason: Docker image pull timeout for ghcr.io/louislam/uptime-kuma:latest after 300s.",
    "resources_used": {
      "duration_seconds": 305,
      "gpu_vram_mb": 0,
      "cpu_time_ms": 8920
    }
  }
}
```

---

### error

**Direction:** Either direction

**Purpose:** Signals protocol errors, agent unavailability, timeouts, or other faults that prevent normal message flow.

**Timing:** Sent when an error condition is detected. May not follow normal request-response pattern.

**Error Information:**

| Field | Type | Description |
|-------|------|-------------|
| `error_code` | int | Error code (5001-5999, see table below) |
| `error_message` | string | Human-readable error message |
| `error_context` | object | Additional context (varies by error code) |

**Example error:**

```json
{
  "type": "error",
  "payload": {
    "error_code": 5005,
    "error_message": "Resource limit exceeded",
    "error_context": {
      "limit_name": "gpu_vram_mb",
      "available": 128,
      "required": 512
    }
  }
}
```

---

## Error Codes

All errors use codes in the range 5001-5999. Error codes are permanent and versioned with the protocol.

| Code | Name | Meaning | Retry | Context |
|------|------|---------|-------|---------|
| 5001 | Timeout | Response not received within deadline | yes | `attempted_retries` (int), `last_attempt` (datetime) |
| 5002 | Agent Unavailable | No connection to agent or broker down | yes | `agent_id` (string), `last_heartbeat` (datetime, nullable) |
| 5003 | Invalid Message | Malformed JSON or missing required fields | no | `validation_error` (string), `field_name` (string, nullable) |
| 5004 | Authentication Failed | Invalid bearer token or signature check failed | no | `agent_id` (string), `token_status` (string) |
| 5005 | Resource Limit Exceeded | GPU VRAM, CPU, or memory exceeded | yes | `limit_name` (string), `available` (int), `required` (int) |
| 5006 | Unsupported Work Type | Unknown work_type requested | no | `work_type_requested` (string), `supported_types` (string[]) |

**Retry Strategy:** Only retry errors marked "yes". Use exponential backoff (see Retries section).

---

## Reliability Patterns

### Timeouts

**Default Timeout:** 30 seconds

The orchestrator waits up to 30 seconds for any response from an agent. This applies to:
- Initial work_request acknowledgment
- work_status updates (if no update in 30s, agent assumed hung)
- work_result delivery

**Per-Task Override:**

Override the default via hints in work_request:

```json
"hints": {
  "max_duration_seconds": 600
}
```

This tells the orchestrator that this particular task may take up to 600 seconds, and not to timeout before that.

**Circuit Breaker:**

After 5 consecutive failures to an agent (timeouts or unavailable errors), the orchestrator stops routing **new** work to that agent for 60 seconds. Existing work continues. After 60s, the orchestrator tries the agent again with a simple health check.

### Retries

**Max Retries:** 3 per message

The orchestrator automatically retries failed messages (up to 3 times) with exponential backoff:

- Attempt 1: No delay
- Attempt 2: 1 second delay
- Attempt 3: 2 seconds delay
- Attempt 4: 4 seconds delay

**Idempotency (Essential!):**

The `request_id` field enables safe retries. Here's how it works:

1. **Orchestrator sends:** `work_request` with `request_id = "xyz123"`
2. **Agent receives:** Checks if it's seen `request_id = "xyz123"` before
3. **If no:** Agent executes the work and **caches the result** with `request_id`
4. **If yes:** Agent returns the cached result (no re-execution)
5. **If network error:** Orchestrator retries with the same `request_id`
6. **Agent responds:** With cached result

This **prevents duplicate work** when the network loses the response.

**Retry Conditions:**

Only retry if the error code is marked "yes" in the Error Codes table above:

| Retryable | Not Retryable |
|-----------|---------------|
| 5001 (Timeout) | 5003 (Invalid Message) |
| 5002 (Agent Unavailable) | 5004 (Authentication Failed) |
| 5005 (Resource Limit) | 5006 (Unsupported Work Type) |

For non-retryable errors, the orchestrator reports the failure to the user immediately.

### Large Payloads

If `work_status` output exceeds 1 MB, the agent splits it across multiple messages:

**Chunking:**

- Agent chunks output in 256 KB blocks
- Each work_status includes: `step.output_chunk = "bytes 0-256k"`
- Next: `step.output_chunk = "bytes 256k-512k"`
- Orchestrator collects and reassembles all chunks

**Example (2 chunks):**

```json
{
  "type": "work_status",
  "payload": {
    "task_id": "...",
    "status": "running",
    "progress_percent": 100,
    "step": {
      "number": 5,
      "name": "Collecting logs",
      "output": "[first 256 KB of output...]",
      "output_chunk": "bytes 0-262144 of 524288"
    }
  }
}
```

Then:

```json
{
  "type": "work_status",
  "payload": {
    "task_id": "...",
    "status": "running",
    "progress_percent": 100,
    "step": {
      "number": 5,
      "name": "Collecting logs",
      "output": "[next 256 KB of output...]",
      "output_chunk": "bytes 262144-524288 of 524288"
    }
  }
}
```

---

## Example: Full Workflow

Here's a complete sequence of a successful deployment:

```
Orchestrator                           Agent
    |                                    |
    |-------- work_request ----------->  |
    |     (task_id, work_type,          |
    |      parameters, hints)           |
    |                                   [validate, start work]
    |                                    |
    | <------ work_status 20% --------- |
    |     (step 1 of 5 complete)        |
    |                                   [continue]
    |                                    |
    | <------ work_status 40% --------- |
    |     (step 2 of 5 complete)        |
    |                                   [continue]
    |                                    |
    | <------ work_status 60% --------- |
    |     (step 3 of 5 complete)        |
    |                                   [continue]
    |                                    |
    | <------ work_status 80% --------- |
    |     (step 4 of 5 complete)        |
    |                                   [continue]
    |                                    |
    | <------ work_status 100% ------- |
    |     (step 5 of 5 complete)        |
    |                                   [finalize]
    |                                    |
    | <------ work_result SUCCESS ----- |
    |     (exit_code=0, output,         |
    |      resources_used)              |
    |                                    |
  [record outcome]                       |
```

---

## Protocol Versioning

**Current Version:** 1.0

**Version Negotiation:**

1. Agent registers supported versions on connect: `["1.0"]` or `["1.0", "2.0"]`
2. Orchestrator picks the lowest common version
3. All messages use that version

**Backwards Compatibility:**

A v2 agent can communicate with a v1 orchestrator by downgrading to v1.0 messages. A v1 agent receiving a v2 message should respond with `error_code=5006` (unsupported work type).

---

## Authentication

**Bearer Token per Agent:**

Each agent has a unique 32-character random token (e.g., `a7f3d8c2e1b9f4a6c8e2d1b3f4a6c8e2`).

**Token Storage:**

- Stored in agent config (not committed to git)
- Loaded from environment variable or config file at startup
- Never logged or exposed

**Token Validation:**

- Orchestrator validates token on every incoming message
- Token passed in Authorization header (REST) or message field (MQ)
- Invalid token → error_code 5004, no retry

**Example with Authorization Header (REST):**

```
POST /api/agent/message HTTP/1.1
Authorization: Bearer a7f3d8c2e1b9f4a6c8e2d1b3f4a6c8e2
Content-Type: application/json

{...message...}
```

---

## Implementation Checklist

- [x] All messages use MessageEnvelope
- [x] Protocol version in all messages (default 1.0)
- [x] Error codes in 5001-5999 range
- [x] Idempotent retries via request_id
- [x] Circuit breaker after 5 failures
- [x] Timeout handling (default 30s, configurable)
- [x] Large payload chunking (256 KB blocks)
- [x] Bearer token authentication
- [x] Full trace IDs for debugging
- [x] Timestamps in ISO 8601 format

---

## References

- **OpenAPI Spec:** `docs/agent-protocol.yaml`
- **Pydantic Models:** `src/common/protocol.py`
- **Exception Classes:** `src/common/exceptions.py`
- **Contract Tests:** `tests/test_protocol_contract.py`
