---
phase: 04-desktop-agent
plan: 03
type: execute
wave: 2
depends_on: ["04-02"]
files_modified:
  - src/agents/base.py
  - src/agents/desktop_agent.py
  - src/orchestrator/service.py
  - tests/test_desktop_agent_heartbeat.py
autonomous: true
must_haves:
  truths:
    - "Desktop agent sends heartbeat every 30s (configurable) with current resource metrics"
    - "Heartbeat message includes all resource metrics in StatusUpdate.resources dict"
    - "Orchestrator receives heartbeat and updates agent_registry.resource_metrics in database"
    - "Orchestrator marks agent offline after 90s (3x heartbeat interval) of no heartbeats"
    - "Agent reconnects automatically after network blips (exponential backoff, max 10 attempts)"
  artifacts:
    - path: src/agents/base.py
      provides: "BaseAgent.start_heartbeat_loop() with config-driven interval and error recovery"
      contains: "heartbeat_interval_seconds from config"
    - path: src/agents/desktop_agent.py
      provides: "DesktopAgent run() method that starts heartbeat loop and work consumer"
      contains: "asyncio.create_task(self.start_heartbeat_loop())"
    - path: src/orchestrator/service.py
      provides: "OrchestratorService.handle_agent_heartbeat() to update agent_registry with metrics"
      contains: "agent.resource_metrics = heartbeat.resources"
    - path: tests/test_desktop_agent_heartbeat.py
      provides: "Integration tests for heartbeat messaging (30+ test cases)"
      min_lines: 400
  key_links:
    - from: "DesktopAgent.start_heartbeat_loop()"
      to: "StatusUpdate message -> RabbitMQ"
      via: "Heartbeat interval from config"
      pattern: "await asyncio.sleep.*heartbeat_interval"
    - from: "RabbitMQ heartbeat message"
      to: "OrchestratorService.handle_agent_heartbeat()"
      via: "Message listener in orchestrator"
      pattern: "work_status.*type"
    - from: "OrchestratorService.handle_agent_heartbeat()"
      to: "agent_registry.resource_metrics"
      via: "Database update"
      pattern: "agent.resource_metrics = heartbeat"
---

<objective>
Integrate heartbeat messaging with resource metrics persistence. Desktop agents send heartbeats every 30s with resource metrics; orchestrator persists metrics to database and marks agents offline if heartbeats stop.

Purpose: Phase 2 BaseAgent has heartbeat loop but uses hardcoded 60s interval and doesn't populate resource_metrics. Phase 3 orchestrator receives heartbeats but doesn't store metrics. Phase 4 requires config-driven 30s heartbeats with metrics persistence for capacity queries.

Output: Updated BaseAgent heartbeat loop, DesktopAgent main run method, OrchestratorService heartbeat handler, comprehensive integration tests.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/04-desktop-agent/04-CONTEXT.md
@.planning/phases/04-desktop-agent/04-RESEARCH.md

## Heartbeat Flow

1. DesktopAgent.start_heartbeat_loop() (runs every heartbeat_interval_seconds from config):
   - Collect resource metrics via _get_resource_metrics()
   - Create StatusUpdate with resources dict
   - Create MessageEnvelope with type="work_status"
   - Publish to reply_queue

2. RabbitMQ routes to orchestrator's reply_queue listener

3. OrchestratorService.handle_agent_heartbeat() receives message:
   - Extract agent_id from StatusUpdate
   - Look up agent in agent_registry DB
   - If new agent: auto-register (homelab context, trust agents)
   - Update last_heartbeat_at = now()
   - Update status = "online"
   - Save resource_metrics = heartbeat.resources (JSON)
   - Commit to DB

4. Offline detection (background task):
   - Periodic check (e.g., every 30s): Find agents with last_heartbeat_at > 90s ago
   - Mark status = "offline"
   - Log offline transition

## Config Integration (from Plan 02)

heartbeat_interval_seconds: 30 (read from config file)
heartbeat_timeout_seconds: 90 (calculate: 3 × interval)

## Error Resilience (from Research)

- Network blips: Agent reconnects with exponential backoff (1s, 2s, 4s, ..., max 60s)
- GPU timeout: Metrics collection failure (5s timeout) doesn't crash agent or stop heartbeat
- RabbitMQ unavailable: Agent retries connection on startup (10 attempts), then exits (let systemd restart)
- Metrics collection error: Log at DEBUG, use cached/empty metrics, don't block heartbeat
</context>

<tasks>

<task type="auto">
  <name>Task 1: Update BaseAgent.start_heartbeat_loop() with config-driven interval and reconnection</name>
  <files>src/agents/base.py</files>
  <action>
Modify BaseAgent.start_heartbeat_loop() method to use config-driven heartbeat interval and implement exponential backoff reconnection logic.

Changes:
1. Update start_heartbeat_loop() method:
   - Read heartbeat_interval_seconds from self.config
   - Replace hardcoded 60-second sleep with config value: await asyncio.sleep(self.config.heartbeat_interval_seconds)
   - Add try/except around entire loop to catch and recover from send errors
   - Log at INFO level when starting loop (with interval)

2. Add reconnection logic to handle RabbitMQ disconnections during heartbeat:
   - Wrap await self.send_heartbeat() in try/except for aio_pika.AMQPConnectionError
   - If connection error:
     - Log warning with attempt count
     - Call await self._connect_with_backoff(max_retries=3) to reconnect
     - On success, log reconnection
     - On failure, exit loop and let run() handle shutdown
   - If other error: log at ERROR, continue loop (don't crash on transient issues)

3. Add _connect_with_backoff() helper method to BaseAgent:
   - Exponential backoff: start at 1s, double each retry (1, 2, 4, 8...), cap at 60s
   - Max 10 retries (or configurable)
   - Log each attempt
   - On final failure: raise exception (handled by run() method)

Example structure:
```python
async def start_heartbeat_loop(self) -> None:
    """Background task that sends heartbeats every interval from config."""
    interval = self.config.heartbeat_interval_seconds
    self.logger.info(f"Starting heartbeat loop, interval={interval}s")

    while True:
        try:
            await asyncio.sleep(interval)
            await self.send_heartbeat()
        except aio_pika.exceptions.AMQPConnectionError as e:
            self.logger.warning(f"Heartbeat publish failed (connection error): {e}")
            try:
                await self._connect_with_backoff(max_retries=3)
            except Exception as reconnect_error:
                self.logger.error(f"Reconnection failed: {reconnect_error}, exiting heartbeat loop")
                break
        except asyncio.CancelledError:
            self.logger.info("Heartbeat loop cancelled")
            break
        except Exception as e:
            self.logger.error(f"Heartbeat error (will retry): {e}")
            # Continue loop, don't crash

async def _connect_with_backoff(self, max_retries: int = 10) -> None:
    """Reconnect to RabbitMQ with exponential backoff."""
    backoff_seconds = 1
    for attempt in range(max_retries):
        try:
            self.logger.info(f"Reconnection attempt {attempt + 1}/{max_retries}")
            await self.connect()
            self.logger.info("Reconnected successfully")
            return
        except aio_pika.exceptions.AMQPConnectionError as e:
            if attempt < max_retries - 1:
                self.logger.warning(f"Attempt {attempt + 1} failed, retrying in {backoff_seconds}s: {e}")
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 60)  # Cap at 60s
            else:
                self.logger.error(f"All {max_retries} reconnection attempts failed")
                raise
```

Do NOT:
- Change send_heartbeat() method itself (Plan 02 already updated it)
- Remove or rename any existing BaseAgent methods
- Break work consumption loop
  </action>
  <verify>
Run: `python -c "from src.agents.desktop_agent import DesktopAgent; from src.common.config import Config; c = Config(); d = DesktopAgent('test', 'desktop', c); import inspect; src = inspect.getsource(d.start_heartbeat_loop); assert 'heartbeat_interval_seconds' in src"` (config-driven interval in source)
Run: `grep -n "_connect_with_backoff" src/agents/base.py` (method exists)
Run: `grep -n "backoff_seconds = min" src/agents/base.py` (exponential backoff capped at 60s)
  </verify>
  <done>
BaseAgent.start_heartbeat_loop() uses config-driven interval. Reconnection logic with exponential backoff implemented. Error handling prevents heartbeat loop crashes.
  </done>
</task>

<task type="auto">
  <name>Task 2: Add DesktopAgent.run() method that integrates heartbeat and work loops</name>
  <files>src/agents/desktop_agent.py</files>
  <action>
Add run() method to DesktopAgent (override from BaseAgent) that starts heartbeat loop and work consumption concurrently.

Method should:
1. Call await self.connect() (inherited from BaseAgent)
2. Log: "Starting desktop agent {self.agent_id}"
3. Create two concurrent tasks:
   - heartbeat_task = asyncio.create_task(self.start_heartbeat_loop())
   - work_task = asyncio.create_task(self.consume_work_requests())
4. Wait for both tasks (use asyncio.gather or explicit waits with error handling)
5. On cancellation or error:
   - Cancel both tasks
   - Wait for cancellation to complete (handle CancelledError)
   - Disconnect from RabbitMQ
   - Log shutdown

6. Graceful shutdown on SIGTERM/SIGINT:
   - Use signal handlers if possible (optional, can be done in main.py instead)
   - Or rely on asyncio cancellation

Example structure:
```python
async def run(self) -> None:
    """Main agent run loop.

    Starts heartbeat loop and work consumer concurrently.
    Both run until agent is stopped.
    """
    try:
        await self.connect()
        self.logger.info(f"Desktop agent {self.agent_id} connected to RabbitMQ")

        # Start both loops concurrently
        heartbeat_task = asyncio.create_task(self.start_heartbeat_loop())
        work_task = asyncio.create_task(self.consume_work_requests())

        # Wait for both (will run indefinitely until cancelled)
        try:
            await asyncio.gather(heartbeat_task, work_task)
        except asyncio.CancelledError:
            self.logger.info("Agent cancelled, stopping loops...")
            heartbeat_task.cancel()
            work_task.cancel()
            try:
                await asyncio.gather(heartbeat_task, work_task)
            except asyncio.CancelledError:
                pass
            raise
    except Exception as e:
        self.logger.error(f"Agent error: {e}", exc_info=True)
    finally:
        await self.disconnect()
        self.logger.info("Desktop agent stopped")
```

Do NOT:
- Override connect() or disconnect() (inherit from BaseAgent)
- Break work request handling
- Change message protocol or queue names
  </action>
  <verify>
Run: `python -c "from src.agents.desktop_agent import DesktopAgent; import inspect; src = inspect.getsource(DesktopAgent.run); assert 'heartbeat_task' in src and 'work_task' in src"` (both tasks created)
Run: `grep -n "asyncio.gather" src/agents/desktop_agent.py` (concurrent task execution)
  </verify>
  <done>
DesktopAgent.run() method creates and manages both heartbeat and work consumption tasks concurrently. Graceful error handling and shutdown logic in place.
  </done>
</task>

<task type="auto">
  <name>Task 3: Add OrchestratorService.handle_agent_heartbeat() to persist resource metrics</name>
  <files>src/orchestrator/service.py</files>
  <action>
Add method to OrchestratorService that receives heartbeat messages and persists resource metrics to database.

Method signature:
```python
async def handle_agent_heartbeat(
    self, heartbeat: StatusUpdate, db: Session
) -> None:
```

Logic:
1. Extract agent_id from heartbeat
2. Look up agent in agent_registry table: db.query(AgentRegistry).filter(AgentRegistry.agent_id == heartbeat.agent_id).first()
3. If agent not found (new agent):
   - Auto-register: Create new AgentRegistry record
   - Set agent_id, agent_type, status="online", last_heartbeat_at=now()
   - Set pool_name from heartbeat or default to "{agent_type}_pool_1"
   - Log: "Auto-registered agent {agent_id}"
4. If agent exists:
   - Update status = "online"
   - Update last_heartbeat_at = func.now()
5. Always update resource_metrics = heartbeat.resources (the dict with CPU, GPU metrics)
6. db.commit()
7. Log at INFO level with sample metrics: f"Heartbeat: agent={agent_id}, gpu_vram={metrics['gpu_vram_available_gb']:.1f}GB, cpu_load={metrics['cpu_load_1min']:.1f}"

Error handling:
- Catch db.commit() errors and log at WARNING (don't crash orchestrator)
- If metric extraction fails, log but continue (don't block heartbeat processing)

Integrate into existing message listener:
- Find where orchestrator receives messages from reply_queue
- Add condition: if envelope.type == "work_status": await self.handle_agent_heartbeat(...)
- Heartbeat messages have agent_id in StatusUpdate payload

Addition: Implement mark_agents_offline() background check
- Add async method: OrchestratorService.mark_agents_offline_periodically()
- Runs every 30s: Query agents with last_heartbeat_at > 90s ago
- Mark them: status = "offline", log at INFO level
- Called once on orchestrator startup via asyncio.create_task()
- Prevents stale agents from being included in capacity queries

Do NOT:
- Change existing RequestDecomposer, WorkPlanner, or AgentRouter logic
- Remove any existing orchestrator methods
- Break work result handling (also on reply_queue)
  </action>
  <verify>
Run: `python -c "from src.orchestrator.service import OrchestratorService; import inspect; src = inspect.getsource(OrchestratorService.handle_agent_heartbeat); assert 'resource_metrics' in src"` (method persists metrics)
Run: `grep -n "handle_agent_heartbeat" src/orchestrator/service.py` (method exists)
Run: `grep -B5 -A5 "work_status" src/orchestrator/service.py | grep "handle_agent_heartbeat"` (integrated into message listener)
Run: `grep -n "mark_agents_offline_periodically" src/orchestrator/service.py` (offline marking method exists)
Run: `grep -n "last_heartbeat_at.*90" src/orchestrator/service.py` (offline threshold 90s present)
  </verify>
  <done>
OrchestratorService.handle_agent_heartbeat() method created. Receives heartbeat, auto-registers new agents, updates resource_metrics in database. Integrated into message listener for work_status type.
  </done>
</task>

<task type="auto">
  <name>Task 4: Create integration tests for heartbeat messaging (30+ test cases)</name>
  <files>tests/test_desktop_agent_heartbeat.py</files>
  <action>
Create comprehensive integration test suite for heartbeat messaging, covering:

1. Heartbeat Format & Structure (5 tests):
   - test_heartbeat_message_has_all_required_fields
   - test_heartbeat_includes_resource_metrics
   - test_heartbeat_status_update_structure
   - test_heartbeat_timestamp_is_utc
   - test_heartbeat_agent_id_correct

2. Resource Metrics Content (8 tests):
   - test_cpu_load_averages_present (1min, 5min)
   - test_cpu_cores_available_calculated
   - test_gpu_vram_metrics_present
   - test_gpu_type_detected_correctly (nvidia, amd, intel, none)
   - test_memory_percent_in_range
   - test_memory_available_gb_positive
   - test_metrics_collection_error_handled (GPU timeout doesn't break heartbeat)
   - test_metrics_use_load_average_not_instantaneous_percent

3. Heartbeat Interval (4 tests):
   - test_heartbeat_sent_every_config_interval (mock time, verify sends at 30s, 60s, 90s)
   - test_config_driven_interval_respected
   - test_heartbeat_continues_on_metrics_error
   - test_heartbeat_loop_starts_on_agent_run

4. Orchestrator Persistence (6 tests):
   - test_handle_agent_heartbeat_updates_registry
   - test_handle_agent_heartbeat_auto_registers_new_agent
   - test_handle_agent_heartbeat_saves_resource_metrics_to_db
   - test_handle_agent_heartbeat_updates_last_heartbeat_at
   - test_handle_agent_heartbeat_sets_status_online
   - test_handle_agent_heartbeat_preserves_existing_capabilities

5. Offline Detection (5 tests):
   - test_agent_marked_offline_after_90s_no_heartbeat
   - test_agent_offline_check_uses_last_heartbeat_at
   - test_offline_agent_not_included_in_capacity_queries
   - test_agent_comes_back_online_on_next_heartbeat
   - test_offline_detection_tolerates_minor_clock_skew

6. Reconnection & Resilience (4 tests):
   - test_agent_reconnects_after_network_blip
   - test_reconnection_uses_exponential_backoff
   - test_heartbeat_loop_survives_metrics_collection_error
   - test_rabbitmq_connection_error_triggers_reconnect

7. Multi-Agent Scenarios (3 tests):
   - test_multiple_agents_register_independently
   - test_orchestrator_tracks_3_agents_separately
   - test_capacity_query_returns_all_agent_metrics

Test implementation notes:
- Use pytest fixtures for: test_agent (DesktopAgent), test_db (SQLAlchemy test session), mock_rabbitmq
- Mock RabbitMQ message queue for heartbeat publishing
- Use monkeypatch to mock time.sleep and time.time() for interval tests
- Use monkeypatch to mock psutil/pynvml for deterministic GPU metrics
- Use actual PostgreSQL test database (via pytest fixture) for persistence tests
- Async tests: use @pytest.mark.asyncio decorator
- Test 3 async backends: asyncio, trio, curio (via parametrize like Phase 2-3 tests)

File structure: ~400-500 lines total

Key test patterns (from existing test files):
```python
@pytest.mark.asyncio
async def test_heartbeat_sent_every_interval(test_agent, config_30s):
    """Verify heartbeat sends at configured interval."""
    # Setup
    heartbeats_sent = []
    original_send = test_agent.send_heartbeat
    async def tracked_send():
        heartbeats_sent.append(time.time())
        await original_send()
    test_agent.send_heartbeat = tracked_send

    # Execute: run heartbeat loop for ~90 seconds (3 heartbeats at 30s interval)
    task = asyncio.create_task(test_agent.start_heartbeat_loop())
    try:
        await asyncio.sleep(90)
    finally:
        task.cancel()

    # Verify: 3 heartbeats sent at ~30s intervals
    assert len(heartbeats_sent) == 3
    # Intervals should be ~30s apart
    ...
```

Do NOT:
- Import test utilities that don't exist yet (use existing Phase 2/3 test patterns)
- Mock _get_resource_metrics() if testing actual metrics (test real psutil output)
- Mock GPU detection unless testing error handling
  </action>
  <verify>
Run: `pytest tests/test_desktop_agent_heartbeat.py -v` (all tests pass, 30+ test methods)
Run: `pytest tests/test_desktop_agent_heartbeat.py::test_heartbeat_message_has_all_required_fields -v` (specific test passes)
Run: `pytest tests/test_desktop_agent_heartbeat.py -k "offline" -v` (offline detection tests: test_agent_marked_offline_after_90s_no_heartbeat, test_agent_offline_check_uses_last_heartbeat_at, test_offline_agent_not_included_in_capacity_queries, test_agent_comes_back_online_on_next_heartbeat, test_offline_detection_tolerates_minor_clock_skew all passing)
Run: `pytest tests/test_desktop_agent_heartbeat.py --co -q | wc -l` (count test methods, should be 30+)
  </verify>
  <done>
Integration test suite created with 30+ test cases covering heartbeat messaging, resource metrics, interval configuration, orchestrator persistence, offline detection, reconnection, and multi-agent scenarios. All tests passing.
  </done>
</task>

</tasks>

<verification>
1. BaseAgent.start_heartbeat_loop() reads interval from config
2. BaseAgent implements exponential backoff reconnection
3. DesktopAgent.run() starts heartbeat and work tasks concurrently
4. OrchestratorService.handle_agent_heartbeat() persists metrics to database
5. Heartbeat messages include all resource metrics
6. Orchestrator marks agents offline after 90s of no heartbeats
7. Auto-registration of new agents on first heartbeat
8. Integration tests cover heartbeat format, intervals, persistence, offline detection
9. All 30+ integration tests passing
</verification>

<success_criteria>
- Config-driven heartbeat intervals (30s default, configurable)
- Heartbeat loop recovers from network errors via exponential backoff
- Resource metrics persisted to database on every heartbeat
- Agents auto-register on first heartbeat (homelab context: trust agents)
- Offline detection marks agents offline after 90s threshold
- Comprehensive integration tests validate full heartbeat flow
- Ready for Plan 04 (orchestrator capacity query endpoints)
</success_criteria>

<output>
After completion, create `.planning/phases/04-desktop-agent/04-03-SUMMARY.md` with:
- Heartbeat integration architecture
- Config-driven interval implementation
- Reconnection strategy (exponential backoff)
- Offline detection logic (90s threshold)
- OrchestratorService heartbeat handler details
- Integration test coverage (30+ test cases)
- Ready-for-Plan-04 status
</output>
