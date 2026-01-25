---
phase: 04-desktop-agent
plan: 05
type: execute
wave: 2
depends_on: ["04-04"]
files_modified:
  - tests/test_desktop_agent_e2e.py
  - tests/test_orchestrator_desktop_integration.py
autonomous: true
must_haves:
  truths:
    - "3 desktop agents can register and send heartbeats simultaneously"
    - "Orchestrator tracks all 3 agents with distinct resource metrics"
    - "Orchestrator can query agent capacity and filter by GPU/CPU requirements"
    - "Offline detection works: agent goes offline, orchestrator detects within 90s"
    - "Agent reconnection works: agent recovers from network blip and resumes heartbeats"
  artifacts:
    - path: tests/test_desktop_agent_e2e.py
      provides: "End-to-end tests for desktop agent lifecycle (20+ test cases)"
      min_lines: 400
    - path: tests/test_orchestrator_desktop_integration.py
      provides: "Integration tests for orchestrator + desktop agents (25+ test cases)"
      min_lines: 500
  key_links:
    - from: "DesktopAgent.run()"
      to: "OrchestratorService.handle_agent_heartbeat()"
      via: "RabbitMQ heartbeat message"
      pattern: "work_status.*message_type"
    - from: "OrchestratorService.handle_agent_heartbeat()"
      to: "GET /api/v1/agents/available-capacity"
      via: "Capacity query after heartbeat"
      pattern: "resource_metrics.*gpu_vram"
---

<objective>
Comprehensive end-to-end testing of Phase 4 desktop agent functionality. Verify multi-agent registration, heartbeat delivery, metrics persistence, offline detection, reconnection, and capacity queries work together correctly.

Purpose: Plans 01-04 implemented individual components (schema, agent metrics, heartbeat loop, API endpoints). Plan 05 validates full integration: multiple agents → orchestrator → capacity queries.

Output: Two test suites (40+ test cases) covering agent lifecycle, multi-agent scenarios, and orchestrator capacity awareness.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/04-desktop-agent/04-CONTEXT.md
@.planning/phases/04-desktop-agent/04-RESEARCH.md

## E2E Test Scenarios

### Desktop Agent Lifecycle (single agent)
1. Agent starts and connects to RabbitMQ
2. Agent sends first heartbeat (registers in orchestrator)
3. Orchestrator persists metrics
4. Agent sends 3-5 consecutive heartbeats
5. Capacity query returns metrics
6. Agent stops gracefully
7. Orchestrator marks offline after threshold

### Multi-Agent Scenarios (3+ agents)
1. Start 3 agents with different capabilities (high VRAM, low VRAM, no GPU)
2. All register independently
3. Orchestrator tracks all 3 with distinct IDs and metrics
4. Capacity query min_gpu_vram=4GB returns only agents 1 & 2
5. Capacity query min_cpu_cores=16 returns subset
6. All agents send heartbeats simultaneously (no interference)

### Offline/Reconnection (resilience)
1. Agent online, heartbeats flowing
2. Simulate network blip (disconnect RabbitMQ)
3. Agent reconnects with exponential backoff
4. Agent resumes heartbeats
5. Orchestrator sees status transition offline→online

### Error Scenarios
1. GPU metrics collection timeout (nvidia-smi hangs)
   - Agent heartbeat continues (metrics = zeros)
   - Orchestrator receives heartbeat with gpu_vram_available_gb = 0
2. Partial metrics failure (only GPU fails, CPU works)
   - Heartbeat includes CPU load but gpu_type = "none"
3. Database transaction error on heartbeat
   - Orchestrator logs error, doesn't crash
   - Next heartbeat retries

## Test Fixtures & Infrastructure

Use pytest patterns from Phase 2-3:
- Async tests: @pytest.mark.asyncio
- Multiple backends: @pytest.mark.parametrize("anyio_backend", ["asyncio", "trio", "curio"])
- RabbitMQ test container: start in conftest.py
- PostgreSQL test database: conftest.py setup
- Mock config: agent_id, heartbeat_interval (short for tests, e.g., 1s)
- Logger capture: check INFO/DEBUG logs for expected messages
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create desktop agent lifecycle E2E tests (20+ test cases)</name>
  <files>tests/test_desktop_agent_e2e.py</files>
  <action>
Create comprehensive end-to-end test suite for desktop agent lifecycle.

Test categories:

1. Single Agent Lifecycle (6 tests):
   - test_agent_starts_connects_registers
   - test_agent_sends_first_heartbeat
   - test_agent_sends_periodic_heartbeats (5 heartbeats over 5s, 1s interval)
   - test_agent_graceful_shutdown (stop → disconnect)
   - test_agent_heartbeat_survives_metrics_error (GPU timeout, continue)
   - test_agent_marked_offline_after_threshold (no heartbeat for 90s)

2. Multi-Agent Startup (4 tests):
   - test_three_agents_start_independently
   - test_all_agents_register_in_orchestrator
   - test_each_agent_has_distinct_id
   - test_no_agent_interference (agent1 metrics != agent2 metrics)

3. Metrics Collection & Reporting (5 tests):
   - test_agent_reports_cpu_load_averages
   - test_agent_reports_gpu_vram (mocked for determinism)
   - test_agent_reports_available_cores (calculated from load)
   - test_metrics_persist_to_database
   - test_heartbeat_includes_all_metric_fields

4. Capacity Query Integration (3 tests):
   - test_single_agent_capacity_query (GET /agents/{id}/capacity)
   - test_query_all_agent_capacity
   - test_capacity_query_matches_heartbeat_metrics (metrics in query match DB)

5. Configuration (2 tests):
   - test_config_driven_heartbeat_interval
   - test_env_var_overrides_config

File structure: ~400-450 lines

Test implementation notes:
- Use test_agent fixture (DesktopAgent with mocked config)
- Use test_db fixture (SQLAlchemy session with agent_registry table)
- Use mock_rabbitmq fixture (in-memory queue or test queue)
- Async tests with asyncio/trio/curio parametrization
- Mock psutil/pynvml for deterministic GPU/CPU metrics
- Mock time.sleep for interval tests (e.g., 5 heartbeats in 5s instead of 150s)
- Verify logs contain expected messages (INFO: "Heartbeat sent", "Auto-registered agent")
- Verify DB contains expected records (agent_registry with resource_metrics)

Example test pattern:
```python
@pytest.mark.asyncio
@pytest.mark.parametrize("anyio_backend", ["asyncio", "trio", "curio"])
async def test_agent_sends_periodic_heartbeats(test_agent, test_db, mock_rabbitmq):
    """Verify agent sends heartbeats at configured interval."""
    # Setup
    heartbeats = []
    async def capture_heartbeat(message):
        heartbeats.append(datetime.utcnow())
        await mock_rabbitmq.append(message)
    test_agent.send_heartbeat = capture_heartbeat

    # Execute: run heartbeat loop for 5s (config interval=1s → 5 heartbeats)
    task = asyncio.create_task(test_agent.start_heartbeat_loop())
    await asyncio.sleep(5.2)  # Wait for 5+ heartbeats
    task.cancel()

    # Verify
    assert len(heartbeats) >= 5
    # Verify ~1s intervals
    for i in range(1, len(heartbeats)):
        delta = (heartbeats[i] - heartbeats[i-1]).total_seconds()
        assert 0.9 < delta < 1.2  # Allow ±10% jitter
```

Do NOT:
- Use real sleep (too slow for tests)
- Skip async/trio/curio parametrization (Phase 2-3 pattern)
- Make tests flaky (use fixed mocks, deterministic timing)
- Break if RabbitMQ unavailable (use mock/test container)
  </action>
  <verify>
Run: `pytest tests/test_desktop_agent_e2e.py -v` (all tests pass)
Run: `pytest tests/test_desktop_agent_e2e.py -k "lifecycle" --co -q | wc -l` (count lifecycle tests, ~6)
Run: `pytest tests/test_desktop_agent_e2e.py -k "heartbeat" -v` (heartbeat tests pass)
Run: `pytest tests/test_desktop_agent_e2e.py::test_three_agents_start_independently -v` (multi-agent test passes)
  </verify>
  <done>
Desktop agent lifecycle E2E test suite created with 20+ test cases. Single-agent lifecycle, multi-agent startup, metrics collection, capacity integration, and configuration tests all passing.
  </done>
</task>

<task type="auto">
  <name>Task 2: Create orchestrator + desktop agent integration tests (25+ test cases)</name>
  <files>tests/test_orchestrator_desktop_integration.py</files>
  <action>
Create comprehensive integration test suite validating orchestrator + desktop agents working together.

Test categories:

1. Agent Registration (5 tests):
   - test_orchestrator_auto_registers_new_agent_on_heartbeat
   - test_orchestrator_creates_agent_registry_record
   - test_agent_id_preserved_across_heartbeats
   - test_pool_name_assigned_on_registration
   - test_new_agent_status_set_online

2. Metric Persistence (5 tests):
   - test_orchestrator_saves_resource_metrics_to_db
   - test_metrics_include_cpu_load_and_cores
   - test_metrics_include_gpu_vram_and_type
   - test_metrics_updated_on_each_heartbeat
   - test_empty_metrics_handled_gracefully (agent hasn't reported yet)

3. Heartbeat Handling (4 tests):
   - test_orchestrator_updates_last_heartbeat_at
   - test_orchestrator_marks_status_online_on_heartbeat
   - test_multiple_agents_heartbeats_processed_independently
   - test_corrupted_heartbeat_message_logged_not_crashed

4. Offline Detection (5 tests):
   - test_agent_offline_after_90s_no_heartbeat
   - test_offline_detection_periodic_check
   - test_offline_agent_excluded_from_capacity_queries
   - test_agent_comes_back_online_on_new_heartbeat
   - test_offline_status_transition_logged

5. Capacity Query Integration (4 tests):
   - test_capacity_query_returns_online_agents_only
   - test_capacity_query_filters_by_gpu_vram
   - test_capacity_query_filters_by_cpu_cores
   - test_capacity_query_returns_all_metrics

6. Multi-Agent Scenarios (2 tests):
   - test_orchestrator_tracks_3_agents_simultaneously
   - test_capacity_query_with_mixed_capabilities (high VRAM, low VRAM, no GPU)

File structure: ~500-550 lines

Test implementation notes:
- Use test_db fixture (real PostgreSQL test database)
- Use mock_orchestrator_service fixture (OrchestratorService instance)
- Use test_agents fixture (create 3 agents with different capabilities)
- Async tests with asyncio/trio/curio parametrization
- Setup agents with different resource profiles:
  - Agent1: high VRAM (8GB), 16 CPU cores
  - Agent2: low VRAM (2GB), 4 CPU cores
  - Agent3: no GPU, 8 CPU cores
- Verify DB records created and updated correctly
- Verify capacity queries return expected agents
- Test edge cases: offline agents, missing metrics, conflicting queries

Example test pattern:
```python
@pytest.mark.asyncio
async def test_capacity_query_filters_by_gpu_vram(test_db, mock_orchestrator_service):
    """Verify capacity query filters agents by GPU VRAM requirement."""
    # Setup: Register 3 agents with different VRAM
    agents = [
        AgentRegistry(agent_id=uuid4(), gpu_vram=8.0, cpu_cores=16, status="online"),
        AgentRegistry(agent_id=uuid4(), gpu_vram=2.0, cpu_cores=4, status="online"),
        AgentRegistry(agent_id=uuid4(), gpu_vram=0.0, cpu_cores=8, status="online"),
    ]
    for agent in agents:
        test_db.add(agent)
    test_db.commit()

    # Execute: Query agents with min_gpu_vram_gb=4.0
    result = await mock_orchestrator_service.get_available_capacity(
        min_gpu_vram_gb=4.0,
        db=test_db
    )

    # Verify: Only agent1 (8GB) returned
    assert len(result) == 1
    assert result[0]["agent_id"] == str(agents[0].agent_id)
    assert result[0]["gpu_vram_available_gb"] == 8.0
```

Do NOT:
- Use real RabbitMQ (mock or use test container)
- Skip async/trio/curio parametrization
- Make tests flaky (deterministic data, no timing assumptions)
- Break if external services unavailable (mock as needed)
  </action>
  <verify>
Run: `pytest tests/test_orchestrator_desktop_integration.py -v` (all tests pass)
Run: `pytest tests/test_orchestrator_desktop_integration.py -k "offline" -v` (offline detection tests pass)
Run: `pytest tests/test_orchestrator_desktop_integration.py -k "capacity" -v` (capacity query tests pass)
Run: `pytest tests/test_orchestrator_desktop_integration.py::test_orchestrator_tracks_3_agents_simultaneously -v` (multi-agent test passes)
Run: `pytest tests/test_orchestrator_desktop_integration.py --co -q | wc -l` (count tests, ~25+)
  </verify>
  <done>
Orchestrator + desktop agent integration test suite created with 25+ test cases. Registration, metric persistence, heartbeat handling, offline detection, capacity queries, and multi-agent scenarios all tested.
  </done>
</task>

<task type="auto">
  <name>Task 3: Run full Phase 4 test suite and verify all passing</name>
  <files>tests/</files>
  <action>
Execute all Phase 4 tests to verify complete integration and readiness for deployment.

Run tests:
1. `pytest tests/test_desktop_agent_e2e.py -v` (20+ tests)
2. `pytest tests/test_orchestrator_desktop_integration.py -v` (25+ tests)
3. `pytest tests/test_desktop_agent_heartbeat.py -v` (30+ tests from Plan 03)
4. `pytest tests/test_orchestrator_capacity_api.py -v` (20+ tests from Plan 04)

Expected results:
- All tests passing (95+/95+)
- No timeout failures
- No flaky tests
- Coverage > 85% of Phase 4 code paths

If any failures:
- Investigate root cause
- Fix implementation (not tests)
- Re-run until all passing

Performance check:
- Full suite should run in < 60 seconds
- No individual test > 5 seconds
  </action>
  <verify>
Run: `pytest tests/test_desktop_agent_e2e.py tests/test_orchestrator_desktop_integration.py tests/test_desktop_agent_heartbeat.py tests/test_orchestrator_capacity_api.py -v --tb=short` (full suite)
Run: `pytest tests/test_desktop_agent*.py tests/test_orchestrator*capacity*.py tests/test_orchestrator*desktop*.py -q` (count tests, target 95+)
Run: `pytest tests/test_desktop_agent*.py tests/test_orchestrator*capacity*.py tests/test_orchestrator*desktop*.py --tb=line -x` (fail on first error)
  </verify>
  <done>
Full Phase 4 test suite executed. All 95+ tests passing. No failures, timeouts, or flaky tests. Test execution < 60s. Coverage > 85%.
  </done>
</task>

</tasks>

<verification>
1. Desktop agent lifecycle E2E tests cover single-agent startup, heartbeat flow, metrics collection, offline detection
2. Multi-agent tests verify 3 agents register independently with distinct metrics
3. Orchestrator integration tests verify heartbeat persistence, metric storage, offline detection
4. Capacity query tests verify filtering by GPU VRAM and CPU cores
5. All 95+ tests passing
6. No test flakiness or timing issues
7. Full suite executes in < 60 seconds
8. Code coverage > 85% for Phase 4 components
</verification>

<success_criteria>
- End-to-end tests for single agent and multi-agent scenarios
- Integration tests for orchestrator + desktop agents
- Offline detection and capacity query testing
- Multi-agent capacity filtering tests
- All 95+ tests passing without flakiness
- Code coverage > 85%
- Full test suite runs efficiently (< 60s)
- Phase 4 implementation complete and verified
</success_criteria>

<output>
After completion, create `.planning/phases/04-desktop-agent/04-05-SUMMARY.md` with:
- E2E test scenarios covered (lifecycle, multi-agent, offline/reconnection, errors)
- Integration test coverage (95+ test cases)
- Multi-agent validation (3 agents with distinct capabilities)
- Capacity query validation (filtering, edge cases)
- Test execution performance (runtime, coverage %)
- Phase 4 completion status and artifact summary
</output>
