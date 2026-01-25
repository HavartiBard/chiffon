---
phase: 02-message-bus
plan: 01
type: execute
wave: 1
depends_on: []
files_modified: [docker-compose.yml, src/common/rabbitmq.py]
autonomous: true
must_haves:
  truths:
    - "RabbitMQ service is running and responding to health checks"
    - "Admin panel (Management UI) is accessible on port 15672"
    - "Test queue can be created and deleted via RabbitMQ CLI commands"
    - "Durable queue topology is declared and persisted"
    - "Priority queue configuration (x-max-priority=5) is set correctly"
  artifacts:
    - path: "src/common/rabbitmq.py"
      provides: "Queue topology declaration, connection factory, channel management"
      exports: ["declare_queues()", "get_connection_string()"]
    - path: "docker-compose.yml"
      provides: "RabbitMQ service definition (already present, verified)"
      contains: "rabbitmq:3.12-management"
  key_links:
    - from: "docker-compose.yml"
      to: "RabbitMQ container"
      via: "service definition with ports 5672 (AMQP) and 15672 (mgmt UI)"
    - from: "src/common/rabbitmq.py"
      to: "docker-compose RabbitMQ"
      via: "amqp://guest:guest@rabbitmq:5672/ connection string from config"
---

<objective>
Deploy RabbitMQ and verify queue topology is correctly configured with durable queues, priority support, and dead-letter exchanges. This plan establishes the foundation for agent communication.

Purpose: RabbitMQ must be operational with production-ready queue configuration before agents can send/receive messages
Output: src/common/rabbitmq.py module with queue topology declaration; verified RabbitMQ service running
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
@/home/james/Projects/chiffon/src/common/config.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create RabbitMQ queue topology module (src/common/rabbitmq.py)</name>
  <files>src/common/rabbitmq.py</files>
  <action>
Create src/common/rabbitmq.py with:

1. Import aio-pika library (will be added to pyproject.toml in plan 02-02)
2. Implement declare_queues() async function that:
   - Accepts a channel: aio_pika.Channel parameter
   - Declares work_queue (durable=True, x-max-priority=5, x-dead-letter-exchange='dlx_exchange')
   - Declares reply_queue (durable=True, x-dead-letter-exchange='dlx_exchange')
   - Declares broadcast_exchange (type=FANOUT, durable=False)
   - Declares dlx_exchange (type=DIRECT, durable=True)
   - Declares dlx_queue (durable=True, x-max-length=10000)
   - Binds dlx_queue to dlx_exchange with routing_key=''
   - Returns dict with keys: 'work_queue', 'reply_queue', 'broadcast_exchange', 'dlx_queue'

3. Implement get_connection_string() function that:
   - Returns RABBITMQ_URL from config (imported from src.common.config)
   - Default fallback: "amqp://guest:guest@localhost:5672/"

4. Add docstrings explaining each queue's purpose (from RESEARCH.md)

5. Include error handling for:
   - Connection failures (log and re-raise for caller to handle)
   - Queue declaration failures (log queue name and error)

Pattern to follow (from RESEARCH.md):
- Use aio_pika.ExchangeType for exchange types
- Durable metadata persists across RabbitMQ restarts
- Priority queue levels 1-5 (not 255 for performance)
- Dead-letter exchange prevents infinite requeue loops

Do NOT implement consumer/publisher logic yet (that's plan 02-03 for agents, plan 02-04 for orchestrator).
  </action>
  <verify>
1. Code style check: ruff check src/common/rabbitmq.py
2. Type check: mypy src/common/rabbitmq.py
3. Syntax check: python -m py_compile src/common/rabbitmq.py
4. Docstring verification: grep -c "def " src/common/rabbitmq.py should be >= 2
  </verify>
  <done>
src/common/rabbitmq.py exists with declare_queues() and get_connection_string() functions. All queues properly typed with Pydantic/aio-pika conventions. No import errors.
  </done>
</task>

<task type="checkpoint:human-verify">
  <name>Task 2: Verify RabbitMQ service is running and accessible</name>
  <files>docker-compose.yml</files>
  <what-built>
RabbitMQ service configuration already exists in docker-compose.yml from Phase 1. This checkpoint verifies it's operational before moving to agent/orchestrator integration.
  </what-built>
  <how-to-verify>
1. Start RabbitMQ if not already running:
   cd /home/james/Projects/chiffon && docker-compose up -d rabbitmq

2. Verify service is healthy (wait ~10s for startup):
   docker-compose ps | grep rabbitmq
   - Status should show "healthy" or "Up"

3. Test AMQP port (5672):
   curl -i amqp://localhost:5672 2>&1 || echo "Expected: connection refused from curl (AMQP protocol, not HTTP)"
   nc -zv localhost 5672
   - Should show: "Connection successful" or similar

4. Access Management UI at:
   http://localhost:15672
   - Username: guest
   - Password: guest
   - Expected: RabbitMQ management dashboard loads (shows Overview, Connections, Channels, Queues, etc.)

5. Verify no queues exist yet:
   - Click "Queues and Streams" in dashboard
   - Should show empty list (Phase 02-01 declares topology, not creates initial queues)

6. Check docker-compose RabbitMQ service config matches RESEARCH.md:
   - Port 5672 (AMQP) exposed: YES
   - Port 15672 (Management UI) exposed: YES
   - Health check present: YES
   - Image: rabbitmq:3.12-management-alpine: YES
  </how-to-verify>
  <resume-signal>
Report back with:
1. Docker container status (healthy/up)
2. AMQP port accessible (connection test)
3. Management UI accessible (http://localhost:15672 loads)
4. Confirm "Queues and Streams" is currently empty

If any issue:
- State the error (e.g., "port 5672 already in use")
- Check logs: docker-compose logs rabbitmq | tail -20
  </resume-signal>
</task>

</tasks>

<verification>
After execution:
1. Code verification: python -m pytest tests/ -k "rabbitmq" -v (no tests yet, will be added in 02-02)
2. Import test: python -c "from src.common.rabbitmq import declare_queues, get_connection_string; print('✓ Module imports successfully')"
3. Docker verification: docker-compose ps | grep -E "rabbitmq|postgres" | grep -c "healthy" should be >= 1
</verification>

<success_criteria>
- src/common/rabbitmq.py created and importable (no syntax errors)
- declare_queues() function signature matches aio_pika.Channel -> dict[str, aio_pika.Queue|aio_pika.Exchange]
- RabbitMQ container running and health check passing (status: healthy)
- Management UI accessible (http://localhost:15672 loads with guest/guest credentials)
- No errors in docker-compose logs related to RabbitMQ
</success_criteria>

<output>
After completion, create `.planning/phases/02-message-bus/02-01-SUMMARY.md` with:
- Timestamp of completion
- RabbitMQ version (from docker-compose)
- Queue topology declared (list: work_queue, reply_queue, broadcast_exchange, dlx_queue)
- Management UI URL and credentials
- Next step reference: "Proceed to 02-02-protocol-PLAN.md"
</output>
