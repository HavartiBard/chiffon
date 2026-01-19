---
phase: 02-message-bus
plan: 05
type: execute
wave: 3
depends_on: [02-01, 02-02, 02-03, 02-04]
files_modified: [tests/test_e2e_message_bus.py]
autonomous: true
must_haves:
  truths:
    - "Orchestrator can dispatch work to agent and receive result with trace_id intact"
    - "Agent receives work, processes, returns result with correlation IDs matching original request"
    - "RabbitMQ persists messages across container restart (durable queue)"
    - "Malformed messages are rejected (NACK) and routed to dead-letter queue"
    - "Idempotency: duplicate work requests return cached result without re-execution"
    - "Error scenarios handled: agent offline, timeout, validation failure, agent crash mid-work"
  artifacts:
    - path: "tests/test_e2e_message_bus.py"
      provides: "End-to-end integration tests for entire message bus"
      contains: "test_orchestrator_to_agent_round_trip"
      min_lines: 300
  key_links:
    - from: "orchestrator (REST API)"
      to: "work_queue"
      via: "aio_pika publish to RabbitMQ"
    - from: "work_queue"
      to: "agent (base.py)"
      via: "aio_pika consume with ACK"
    - from: "agent"
      to: "reply_queue"
      via: "aio_pika publish result"
    - from: "reply_queue"
      to: "orchestrator (background task)"
      via: "aio_pika consume results"
---

<objective>
Validate the complete message bus system end-to-end: orchestrator dispatches work via RabbitMQ to agents, agents process and return results, orchestrator receives and stores results. Test error scenarios, idempotency, message persistence, and dead-letter handling. This is the final validation before moving to agent-specific implementations.

Purpose: Message bus is the backbone of the system; must be reliable, durable, and error-tolerant
Output: tests/test_e2e_message_bus.py with comprehensive end-to-end integration tests
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
@/home/james/Projects/chiffon/docker-compose.yml
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create comprehensive end-to-end integration tests (tests/test_e2e_message_bus.py)</name>
  <files>tests/test_e2e_message_bus.py</files>
  <action>
Create tests/test_e2e_message_bus.py with end-to-end integration tests that exercise the full message bus:

1. Test fixtures and setup:
   - @pytest.fixture rabbitmq_service:
     * Start RabbitMQ via docker-compose (or assume it's already running from earlier setup)
     * Declare queues and exchanges
     * Yield to tests
     * Cleanup on teardown (clear queues)

   - @pytest.fixture orchestrator_service:
     * Create OrchestratorService instance
     * Connect to RabbitMQ
     * Yield to tests
     * Disconnect on teardown

   - @pytest.fixture test_agent:
     * Create TestAgent instance
     * Don't start it yet (tests will control when)
     * Yield to tests

   - @pytest.fixture test_config:
     * Returns config with test DATABASE_URL and RABBITMQ_URL

2. Round-trip tests (5 tests):
   - test_orchestrator_to_agent_round_trip:
     * Orchestrator dispatches work_request with trace_id=A, request_id=B
     * Agent consumes, validates, executes, publishes work_result with same trace_id=A, request_id=B
     * Orchestrator receives result, verifies trace_id and request_id match
     * Assert result.status == 'completed'

   - test_work_round_trip_with_parameters:
     * Dispatch work with parameters: {input: "echo test"}
     * Agent processes, returns output matching input
     * Verify output in result

   - test_work_round_trip_with_priority:
     * Dispatch high-priority work (priority=5)
     * Dispatch low-priority work (priority=1)
     * Verify high-priority is processed first (approximately, may be fuzzy due to timing)

   - test_multiple_agents_process_work:
     * Create 2 TestAgent instances
     * Dispatch 4 work requests
     * Verify all 4 are processed by agents (2 each)
     * All have correct trace_id and request_id

   - test_correlation_ids_propagate:
     * Dispatch work with specific trace_id and request_id
     * Query orchestrator status endpoint
     * Verify returned trace_id and request_id match

3. Error scenario tests (6 tests):
   - test_malformed_message_nacked_to_dlx:
     * Publish invalid JSON to work_queue
     * Verify message is NACK'd and routed to dlx_queue
     * Verify message does not requeue

   - test_invalid_envelope_nacked_to_dlx:
     * Publish JSON that doesn't match MessageEnvelope schema
     * Verify NACK to DLX

   - test_agent_crash_leaves_message_in_queue:
     * Agent consumes message but crashes before ACK
     * Simulate: send work, kill agent connection mid-processing (mock)
     * Message should still be in work_queue (unacked)
     * Another agent or retry should pick it up

   - test_agent_timeout_handled:
     * Agent processes slow_echo (5 second) work
     * Orchestrator has timeout < 5 seconds (if applicable, or test manually)
     * Verify timeout is detected (or agent completes if within timeout)

   - test_duplicate_request_id_returns_cached_result:
     * Agent processes work with request_id=A
     * Before cache expires (300s), dispatch same request_id=A again
     * Agent should return cached result without re-executing
     * Verify both responses are identical

   - test_agent_offline_status_detected:
     * Agent sends heartbeat (status=online)
     * Agent connection drops (simulate: close connection)
     * Wait >180s (3 missed heartbeats)
     * Orchestrator marks agent as offline
     * Verify orchestrator.is_agent_online(agent_id) returns False

4. Message persistence tests (3 tests):
   - test_durable_queue_survives_restart:
     * Publish work_request to work_queue
     * Restart RabbitMQ container (docker-compose restart rabbitmq)
     * Verify message is still in work_queue after restart
     * Agent can still consume it

   - test_priority_queue_ordering:
     * Publish 5 messages with priorities: 1, 3, 5, 2, 4
     * Single consumer processes them
     * Verify consumed order is approximately 5, 4, 3, 2, 1 (higher priority first)
     * NOTE: Order may not be strict FIFO with multiple consumers; test with single consumer

   - test_dead_letter_queue_captures_failures:
     * Publish 10 malformed messages
     * Verify dlx_queue has 10 messages
     * Verify dlx_queue survives RabbitMQ restart

5. Concurrency tests (3 tests):
   - test_concurrent_dispatch_and_consume:
     * Run orchestrator.dispatch_work() in parallel (5 concurrent calls)
     * Run agent.consume_work_requests() concurrently
     * Verify all 5 works are processed
     * No message loss or duplication

   - test_agent_registry_updates_concurrently:
     * Create 3 agents
     * All send heartbeats concurrently
     * Verify agent_registry is updated correctly (no lost updates)
     * All 3 agents registered and online

   - test_result_listener_handles_concurrent_results:
     * Dispatch 5 works
     * Agents process and publish results concurrently
     * Orchestrator result listener processes all results
     * Verify all 5 stored in PostgreSQL with correct status/output

6. Idempotency tests (2 tests):
   - test_request_cache_prevents_duplicate_execution:
     * Dispatch work with request_id=A
     * Agent executes and caches result
     * Dispatch same request_id=A again (within 300s)
     * Agent should skip execution and return cached result
     * Verify execution log shows only 1 execution, not 2

   - test_idempotency_cache_expires:
     * Dispatch work with request_id=A
     * Agent caches result
     * Wait 301 seconds (cache TTL=300s)
     * Dispatch same request_id=A again
     * Agent should re-execute (cache expired)
     * Verify execution log shows 2 executions

7. Health and diagnostics tests (2 tests):
   - test_queue_depth_query:
     * Dispatch 5 works
     * Query work_queue depth
     * Verify depth == 5 or close (depending on whether agents are consuming)
     * Consume all, verify depth == 0

   - test_dlx_queue_inspection:
     * Publish 5 malformed messages
     * Query dlx_queue depth
     * Verify depth >= 5
     * Inspect DLX messages and verify they're malformed

Expected test file size: ~400-500 lines of code.

Important notes:
- Use asyncio and pytest-asyncio for async tests
- Use mock/patch sparingly; prefer real RabbitMQ and PostgreSQL for true integration testing
- If RabbitMQ is not available, skip tests with @pytest.mark.skip(reason="RabbitMQ not available")
- Use small timeouts (e.g., asyncio.wait_for(..., timeout=5)) to avoid tests hanging
- Clean up queues between tests to avoid state leakage
  </action>
  <verify>
1. Syntax: python -m py_compile tests/test_e2e_message_bus.py
2. Run tests: pytest tests/test_e2e_message_bus.py -v
   - May skip some tests if RabbitMQ not running (expected with mark.skip)
   - Critical tests should pass: round_trip, error_nack_to_dlx, concurrent_dispatch
3. Count tests: grep -c "^def test_" tests/test_e2e_message_bus.py should be >= 20
4. Coverage: pytest tests/test_e2e_message_bus.py --cov=src.orchestrator --cov=src.agents --cov-report=term-missing
  </verify>
  <done>
tests/test_e2e_message_bus.py created with 20+ end-to-end integration tests. Tests cover round-trip, error scenarios, persistence, concurrency, idempotency, and health.
  </done>
</task>

</tasks>

<verification>
After execution:
1. Ensure RabbitMQ and PostgreSQL are running:
   docker-compose ps | grep -E "rabbitmq|postgres" should show both healthy

2. Run integration tests:
   pytest tests/test_e2e_message_bus.py -v

3. Manual smoke test (optional):
   - Start orchestrator: python -m src.orchestrator.main
   - In another terminal, start test agent: python -m src.agents.test_agent
   - Dispatch work via REST: curl -X POST http://localhost:8000/api/v1/dispatch ...
   - Check result: curl http://localhost:8000/api/v1/status/{task_id}
   - Verify trace_id matches in all calls

4. RabbitMQ Management UI inspection:
   - Open http://localhost:15672 (guest/guest)
   - Check Queues: work_queue, reply_queue, dlx_queue should exist and be durable
   - Check Connections: should see agent and orchestrator connections
   - Check Channels: should see separate channels for publishing and consuming
</verification>

<success_criteria>
- tests/test_e2e_message_bus.py created with 20+ integration tests
- Round-trip tests pass: orchestrator -> work_queue -> agent -> reply_queue -> orchestrator
- Error scenarios tested: malformed messages, agent offline, timeouts
- Persistence verified: durable queues survive container restart
- Idempotency working: duplicate request_ids return cached results
- Concurrency tested: multiple agents and concurrent dispatches work
- Message correlation verified: trace_id and request_id propagate end-to-end
- Dead-letter queue captures unrecoverable messages
</success_criteria>

<output>
After completion, create `.planning/phases/02-message-bus/02-05-SUMMARY.md` with:
- Integration test count (e.g., 24 tests)
- Test categories covered (round-trip, errors, persistence, concurrency, idempotency, health)
- RabbitMQ topology verified (queues, exchanges, routing)
- PostgreSQL task tracking verified
- Critical test results (all pass, or note which skip due to missing services)
- Phase 2 completion: All 5 plans complete, message bus operational
- Next step reference: "Phase 2 validation complete. Proceed to Phase 3: Orchestrator Core or Phase 4: Desktop Agent"
</output>
