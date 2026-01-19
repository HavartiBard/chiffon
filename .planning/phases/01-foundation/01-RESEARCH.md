# Phase 1: Foundation & Observability Infrastructure - Research

**Researched:** 2026-01-19
**Domain:** PostgreSQL schema design, Docker dev environment, agent protocol specification, Python ecosystem
**Confidence:** HIGH (PostgreSQL, Docker, FastAPI), MEDIUM (LiteLLM vendor routing), LOW (Ollama performance)

## Summary

Phase 1 foundation work centers on five interconnected technical domains: PostgreSQL audit schema, Docker Compose orchestration, agent protocol specification, Python dependency management, and LiteLLM vendor fallback integration. Research identifies the standard stack and critical pitfalls that could derail the foundation and cause expensive refactoring later.

**Key findings:**
1. Alembic autogenerate cannot detect table/column renames or custom SQLAlchemy types — manual migration review is non-negotiable
2. Docker Compose health checks with `depends_on: {condition: service_healthy}` is the standard pattern; otherwise services start before dependencies are ready
3. Agent protocols require explicit idempotency tokens (request_id) to handle retries without duplicate work; A2A protocol (2026) validates this pattern
4. PostgreSQL JSONB performance degrades 2-10x for objects >2KB due to TOAST — split large outputs to separate tables
5. Poetry lock file must never be manually edited; version mismatches across Python versions cause CI/CD failures
6. LiteLLM fallback routing requires models to be registered in model_list; unregistered fallbacks fail silently

**Primary recommendation:** Invest Phase 1 time in: (1) solid Alembic migration scaffolding with pre-deployment review process, (2) Docker health checks before dependent service startup, (3) explicit protocol idempotency in first message implementation, (4) splitting large JSONB outputs to avoid TOAST performance cliffs.

---

## Standard Stack

### Core Infrastructure

| Component | Version | Purpose | Confidence |
|-----------|---------|---------|------------|
| PostgreSQL | 15+ | Operational state, task tracking, execution logs | HIGH |
| RabbitMQ | 3.12+ with management plugin | Agent work dispatch + status replies | HIGH |
| Alembic | 1.18+ | Schema version control, migrations | HIGH |
| Docker Compose | 2.20+ | Local dev orchestration | HIGH |
| Ollama | Latest (neural-chat model) | Local LLM fallback, zero-cost inference | MEDIUM |
| LiteLLM | 1.30+ (proxy mode) | Vendor-agnostic LLM access, fallback chains | MEDIUM |

### Python Runtime & Testing

| Component | Version | Purpose | Confidence |
|-----------|---------|---------|------------|
| Python | 3.11+ | Runtime | HIGH |
| Poetry | 1.7+ | Dependency lock, reproducible builds | HIGH |
| FastAPI | 0.109+ | HTTP API + WebSocket support | HIGH |
| SQLAlchemy | 2.0+ | ORM, connection pooling | HIGH |
| Pydantic | 2.0+ | Data validation, schema generation | HIGH |
| pytest | 7.4+ | Test framework | HIGH |
| pytest-postgresql | 6.0+ | Isolated test databases | HIGH |
| pytest-docker or Testcontainers | Latest | Test database containers | MEDIUM |
| pika | 1.3+ | RabbitMQ AMQP client | HIGH |
| python-dotenv | 1.0+ | .env secrets loading | HIGH |

### Code Quality

| Component | Version | Purpose | Confidence |
|-----------|---------|---------|------------|
| black | 24+ | Code formatting | HIGH |
| ruff | 0.3+ | Linting (replaces flake8/isort) | HIGH |
| mypy | 1.8+ (optional) | Type checking | MEDIUM |

### Installation (pyproject.toml)

```toml
[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.109.0"
sqlalchemy = "^2.0"
pydantic = "^2.0"
pydantic-settings = "^2.0"
alembic = "^1.18"
pika = "^1.3"
psycopg = {extras = ["binary"], version = "^3.1"}
python-dotenv = "^1.0"
uvicorn = "^0.27"
litellm = "^1.30"

[tool.poetry.group.dev.dependencies]
pytest = "^7.4"
pytest-postgresql = "^6.0"
pytest-asyncio = "^0.23"
pytest-cov = "^4.1"
black = "^24.0"
ruff = "^0.3"
mypy = "^1.8"
```

---

## Architecture Patterns

### Recommended Project Structure

```
agent-deploy/
├── .planning/                          # GSD planning (locked decisions)
├── src/
│   ├── __init__.py
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI app initialization
│   │   ├── models.py                  # Pydantic schemas + SQLAlchemy ORM
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── work_requests.py       # POST /work endpoint
│   │   │   └── status.py              # Query endpoints
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── connection.py          # Engine, session factory, pooling
│   │   │   ├── queries.py             # Helper functions (find_task, log_execution)
│   │   │   └── health.py              # Health check queries
│   │   └── mq/
│   │       ├── __init__.py
│   │       ├── publisher.py           # Send work_request to agents
│   │       ├── consumer.py            # Listen for work_status/work_result
│   │       └── protocol.py            # Message validation (envelope checks)
│   └── common/
│       ├── __init__.py
│       ├── schemas.py                 # Shared message types (work_request, work_result, error)
│       └── logging.py                 # Structured JSON logging
├── tests/
│   ├── __init__.py
│   ├── conftest.py                    # pytest-postgresql fixture setup
│   ├── unit/
│   │   └── test_protocol.py           # Protocol envelope validation
│   ├── integration/
│   │   ├── test_db_schema.py          # Task/execution_logs tables
│   │   └── test_message_format.py     # Work_request/work_result parsing
│   └── contract/
│       └── test_protocol_contract.py  # Validate all messages conform to schema
├── migrations/                         # Alembic
│   ├── versions/
│   │   └── 001_init_schema.py
│   ├── env.py
│   └── script.py.mako
├── docs/
│   ├── PROTOCOL.md                    # Human-readable examples
│   └── agent-protocol.yaml            # OpenAPI spec (machine-readable)
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── poetry.lock
├── .env.example
├── .gitignore
├── ruff.toml                          # or pyproject.toml [tool.ruff] section
└── README.md
```

### Pattern 1: Alembic Migration Workflow

**What:** Schema version control via numbered migration files, applied in order on deployments.

**When to use:** Every schema change (new table, column, index, constraint).

**Critical constraint:** Autogenerate is NOT automatic—it generates candidates that must be manually reviewed.

**Example:**

```python
# migrations/versions/001_init_schema.py
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    op.create_table(
        'tasks',
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('request_text', sa.Text, nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'approved', 'executing',
                  'completed', 'failed', 'rejected', name='task_status'),
                  default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('estimated_resources', postgresql.JSONB, nullable=True),
        sa.Column('actual_resources', postgresql.JSONB, nullable=True),
        sa.Column('external_ai_used', postgresql.JSONB, nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
    )
    op.create_index('ix_tasks_created_at', 'tasks', ['created_at'])
    op.create_index('ix_tasks_status', 'tasks', ['status'])

def downgrade():
    op.drop_index('ix_tasks_status', 'tasks')
    op.drop_index('ix_tasks_created_at', 'tasks')
    op.drop_table('tasks')
```

**Deployment workflow:**
```bash
# Local dev: run all migrations
poetry run alembic upgrade head

# Verify schema
poetry run alembic current

# Rollback if needed (only in dev)
poetry run alembic downgrade -1
```

**Key:** Every migration must include both `upgrade()` and `downgrade()` functions, even if you never rollback in production. This catches design mistakes early.

### Pattern 2: Docker Compose Health Checks & Startup Order

**What:** Use `depends_on` with `condition: service_healthy` to enforce database readiness before dependent services start.

**When to use:** For PostgreSQL, RabbitMQ, or any service that needs initialization time before accepting connections.

**Example:**

```yaml
version: '3.8'
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: agent_deploy
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres_local
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "postgres", "-d", "agent_deploy"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    ports:
      - "5432:5432"

  rabbitmq:
    image: rabbitmq:3.12-management
    environment:
      RABBITMQ_DEFAULT_USER: guest
      RABBITMQ_DEFAULT_PASS: guest
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 15s
    ports:
      - "5672:5672"
      - "15672:15672"

  ollama:
    image: ollama/ollama:latest
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
    ports:
      - "11434:11434"

  litellm:
    image: ghcr.io/berriai/litellm:latest
    depends_on:
      ollama:
        condition: service_healthy
    environment:
      OLLAMA_API_BASE: "http://ollama:11434"
      # Add API keys via .env or secrets
    ports:
      - "8000:8000"

  orchestrator:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
      litellm:
        condition: service_started
    environment:
      DATABASE_URL: "postgresql://postgres:postgres_local@postgres:5432/agent_deploy"
      RABBITMQ_URL: "amqp://guest:guest@rabbitmq:5672/"
      LITELLM_API_URL: "http://litellm:8000"
    ports:
      - "8001:8001"
```

**Critical:** `depends_on` alone (without health checks) starts services in order but does NOT wait for readiness. Use `condition: service_healthy` to block dependent startup until the service is actually ready.

### Pattern 3: Agent Protocol Message Validation

**What:** Every message conforms to a JSON envelope with protocol_version, message_id, request_id, trace_id, and type-specific payload.

**When to use:** Before putting message on RabbitMQ, validate the envelope. On receive, validate before unpacking.

**Example:**

```python
# src/common/schemas.py
from pydantic import BaseModel, Field, field_validator
from typing import Any, Literal
from uuid import UUID

class MessageEnvelope(BaseModel):
    """Base envelope for all protocol messages."""
    protocol_version: str = Field(default="1.0")
    message_id: UUID
    from_agent: Literal["orchestrator", "infra", "desktop", "code", "research"]
    to_agent: Literal["orchestrator", "infra", "desktop", "code", "research"]
    timestamp: str  # ISO 8601
    trace_id: UUID
    request_id: UUID  # For idempotency: if agent sees same request_id, return cached result
    type: Literal["work_request", "work_status", "work_result", "error"]
    payload: dict[str, Any]
    x_custom_fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator('protocol_version')
    @classmethod
    def validate_protocol_version(cls, v):
        if v != "1.0":
            raise ValueError("Unsupported protocol version")
        return v

class WorkRequest(MessageEnvelope):
    type: Literal["work_request"]
    payload: dict = Field(...)

    @field_validator('payload')
    @classmethod
    def validate_payload(cls, v):
        required = {'task_id', 'work_type', 'parameters', 'hints'}
        if not required.issubset(v.keys()):
            raise ValueError(f"Missing required fields: {required - v.keys()}")
        return v

# src/orchestrator/mq/protocol.py
from common.schemas import MessageEnvelope, WorkRequest
import json

def validate_and_parse_message(raw_json: str) -> MessageEnvelope:
    """Parse + validate incoming message against schema."""
    try:
        data = json.loads(raw_json)
        envelope = MessageEnvelope(**data)
        return envelope
    except ValueError as e:
        # Log validation error, send error response with error_code 5003
        raise ProtocolError(code=5003, message=str(e))

def serialize_message(envelope: MessageEnvelope) -> str:
    """Serialize + validate outgoing message."""
    return envelope.model_dump_json()
```

### Pattern 4: SQLAlchemy Connection Pooling for Production

**What:** Use QueuePool with health checks to ensure connections stay alive across deployments.

**When to use:** FastAPI app startup, for all database operations.

**Example:**

```python
# src/orchestrator/db/connection.py
from sqlalchemy import create_engine, event
from sqlalchemy.pool import QueuePool
import os

DATABASE_URL = os.getenv("DATABASE_URL",
    "postgresql://postgres:postgres_local@localhost:5432/agent_deploy")

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,                  # Maintain 20 connections
    max_overflow=10,               # Allow up to 10 additional connections
    pool_timeout=30,               # Wait 30s for a connection
    pool_recycle=3600,             # Recycle connections every hour (PostgreSQL idle timeout)
    pool_pre_ping=True,            # Test connection before giving to app (fixes stale connections)
    echo=False,                    # Set to True for SQL debugging
)

# Verify connection on startup
@app.on_event("startup")
async def startup():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            logger.info("Database connection successful")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise
```

### Anti-Patterns to Avoid

- **Manual poetry.lock edits:** Breaks version guarantees; always regenerate via `poetry lock`
- **Skipping health checks in docker-compose:** Services appear to start but aren't ready; causes random failures
- **Alembic autogenerate without review:** Will miss table/column renames, Enum types, custom constraints; always manually verify
- **Large JSONB outputs (>2KB) in single column:** Triggers TOAST compression, 2-10x slowdown; split to separate table or archive
- **Message processing without idempotency check:** Retries cause duplicate work; always check request_id before executing

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Database schema versioning | Custom migration scripts | Alembic | Version control, rollback, reproducibility, Django/FastAPI ecosystem standard |
| Connection pooling | Manual connection creation per request | SQLAlchemy QueuePool | Connection reuse, timeout handling, stale connection detection (pool_pre_ping) |
| AMQP protocol + retries | Raw socket communication | Pika + RabbitMQ | Built-in heartbeats, acknowledgments, publisher confirmations; handles network failures |
| Message validation | String parsing, ad-hoc checks | Pydantic models | Type safety, consistent validation, OpenAPI schema generation |
| Container orchestration + startup order | bash wait-for-it scripts | Docker Compose health checks | Native, declarative, prevents race conditions |
| Local testing database | Spin up PostgreSQL manually each test | pytest-postgresql | Automatic isolation, cleanup, fast templating, no manual teardown |
| LLM vendor abstraction | Switch code when switching providers | LiteLLM proxy | Single endpoint, fallback routing, cost tracking, no code changes |

**Key insight:** All of these "look simple" in small scope but explode in complexity at scale. Connection pooling edge cases, migration ordering, and AMQP reliability are mature problems with standard solutions.

---

## Common Pitfalls

### Pitfall 1: Alembic Autogenerate Incomplete Detection

**What goes wrong:** You add a table rename, custom Enum, or complex constraint. You run `alembic revision --autogenerate`. Migration is generated but is incomplete or wrong. You deploy it and the schema drifts.

**Why it happens:** Alembic autogenerate uses SQLAlchemy reflection, which cannot detect: table/column renames (appears as drop + add), custom SQLAlchemy types (falls back to CHAR+CHECK), sequences, and PRIMARY KEY changes.

**How to avoid:**
1. Always manually review autogenerated migrations before committing
2. Add a pre-deployment step in CI: `alembic current` to ensure your local schema matches expected version
3. For renames, write the migration manually (use `op.alter_table()` + `op.execute()`)
4. Never rename via drop + recreate; explicitly use `op.execute(ALTER TABLE ... RENAME COLUMN ...)`

**Warning signs:**
- Migration creates new column + drops old one (should be `ALTER ... RENAME`)
- Migration creates CHECK constraints instead of proper Enum columns
- Test database schema doesn't match prod after deployment

**Preventive code:**
```python
# In 001_init_schema.py, explicitly name all constraints
from sqlalchemy.schema import CreateTable

# Good: explicit naming
tasks = sa.Table(
    'tasks',
    metadata,
    sa.Column('status', postgresql.ENUM(..., name='task_status'), ...),
    sa.UniqueConstraint('task_id', 'created_at', name='uq_task_created'),
)

# Don't: let SQLAlchemy auto-name
tasks = sa.Table(
    'tasks',
    metadata,
    sa.Column('status', postgresql.ENUM(...), ...),  # Unnamed — hard to detect
)
```

### Pitfall 2: Docker Compose Service Startup Race Conditions

**What goes wrong:** PostgreSQL container starts but isn't ready to accept connections. Orchestrator service tries to connect immediately, fails. Container is "running" but not "healthy."

**Why it happens:** `depends_on` without health checks just waits for container to start, not for the service inside to be ready. PostgreSQL needs time to initialize WAL, create default databases, and start listening.

**How to avoid:**
1. Define health check for every service that needs initialization time
2. Use `condition: service_healthy` for all dependent services
3. Use appropriate health check commands:
   - PostgreSQL: `pg_isready -U postgres -d agent_deploy`
   - RabbitMQ: `rabbitmq-diagnostics -q ping`
   - Ollama: `curl -f http://localhost:11434/api/tags`

**Warning signs:**
- Orchestrator logs show "connection refused" in first few seconds
- Tests fail intermittently, pass on retry
- `docker-compose logs orchestrator` shows connection errors but database seems running

**Testing pattern:**
```bash
# This should block until services are healthy, not start immediately
docker-compose up -d
sleep 2  # Should not be needed if health checks are correct

# Verify PostgreSQL is healthy
docker-compose exec postgres pg_isready -U postgres
# Should return: "accepting connections"
```

### Pitfall 3: LiteLLM Fallback Model Not Registered

**What goes wrong:** You configure fallback chain: Claude → GPT-4 → Ollama. Claude quota exhausted, router tries to fallback to GPT-4. GPT-4 model is not in `model_list`. Request fails with `BadRequestError`.

**Why it happens:** LiteLLM's router requires all models (primary + fallbacks) to be explicitly registered in `config.json` model_list. A missing fallback silently fails routing.

**How to avoid:**
1. In `config.json`, every model in the fallback chain must be in `model_list`
2. Test fallback chain before deployment: simulate primary quota exhaustion, verify fallback triggers
3. Log which model was selected for each request; monitor fallback rates

**Warning signs:**
- BadRequestError when attempting fallback: `Model GPT-4 not found in model_list`
- Requests fail when Claude quota exhausted instead of falling back
- LiteLLM logs show "skipping unsupported model"

**Configuration pattern:**
```json
{
  "litellm": {
    "model_list": [
      {"model_name": "claude-opus", "litellm_params": {"model": "claude-3-opus-20240229", "api_key": "..."}},
      {"model_name": "gpt-4-turbo", "litellm_params": {"model": "gpt-4-turbo", "api_key": "..."}},
      {"model_name": "ollama-neural", "litellm_params": {"model": "ollama/neural-chat"}}
    ],
    "fallback_strategy": ["claude-opus", "gpt-4-turbo", "ollama-neural"]
  }
}

# All models in fallback_strategy MUST exist in model_list
```

### Pitfall 4: JSONB Performance Cliff at 2KB

**What goes wrong:** Agent execution logs are stored as JSONB in the `output_full` column. Logs for a 10-minute Ansible playbook run are 5MB. Queries on the tasks table become slow (2-10x slower). Eventually queries timeout.

**Why it happens:** PostgreSQL TOAST (The Oversized-Attribute Storage Technique) compresses and externally stores values >2KB. Decompression on query is expensive. JSONB doesn't store statistics for values inside columns, so query optimizer makes poor choices.

**How to avoid:**
1. Keep JSONB objects small (<2KB)
2. For large outputs, store only a summary in JSONB; keep full output in separate table or external file
3. Use `pg_size_pretty()` to monitor column sizes

**Warning signs:**
- Queries on tasks table are slow even with indexes
- `EXPLAIN ANALYZE` shows high planning time on JSONB columns
- Dashboard queries that worked fast now timeout

**Schema pattern (split JSONB):**
```python
# Instead of: one big output_full JSONB

# Do: summary in task, details in separate table
op.create_table(
    'tasks',
    sa.Column('output_summary', postgresql.JSONB, nullable=True),  # <2KB
    # ... other columns
)

op.create_table(
    'execution_output',
    sa.Column('output_id', postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tasks.task_id')),
    sa.Column('output_full', postgresql.TEXT, nullable=True),  # Store as TEXT, not JSONB
    sa.Column('output_size_bytes', sa.Integer),
    sa.Column('created_at', sa.DateTime(timezone=True)),
)

op.create_index('ix_execution_output_task_id', 'execution_output', ['task_id'])
```

### Pitfall 5: Message Idempotency Tokens Missing

**What goes wrong:** Orchestrator sends work_request to infra agent. Network is flaky. Request times out after 3 seconds. Orchestrator retries. Agent receives message twice. Ansible playbook runs twice. Service is deployed twice.

**Why it happens:** Without explicit idempotency tokens, agent cannot distinguish between "new request" and "retry of same request." Retries cause duplicate work.

**How to avoid:**
1. Every message must include a unique `request_id` (UUID)
2. Agent checks if `request_id` has been seen before
3. If seen and completed, return cached result instead of re-executing
4. If seen and in progress, wait for completion

**Warning signs:**
- Duplicate deployments in logs when network is unreliable
- Same Ansible playbook running twice with same parameters
- Agent processes same request_id multiple times

**Implementation pattern:**
```python
# src/orchestrator/mq/consumer.py
from common.schemas import WorkRequest
import redis  # or any KV store

request_cache = {}  # In-memory for MVP; use Redis for production

async def handle_work_request(message: WorkRequest):
    """
    Process work request.
    If request_id seen before, return cached result.
    Otherwise execute and cache.
    """
    request_id = message.request_id

    # Check if already processed
    if request_id in request_cache:
        cached_result = request_cache[request_id]
        logger.info(f"Request {request_id} already processed, returning cached result")
        return send_cached_result(cached_result)

    # Mark as in progress
    request_cache[request_id] = {"status": "processing"}

    try:
        result = await execute_work(message)
        request_cache[request_id] = {"status": "completed", "result": result}
        return send_work_result(result)
    except Exception as e:
        request_cache[request_id] = {"status": "failed", "error": str(e)}
        raise
```

### Pitfall 6: Poetry Version Mismatches Across Environments

**What goes wrong:** You run `poetry add sqlalchemy` on your Mac with Python 3.11. Dependency hash is computed. You commit poetry.lock. CI runs with Python 3.12. Hash doesn't match. Build fails.

**Why it happens:** Poetry generates hash based on your Python version + platform. If CI uses different Python version, hash is invalid.

**How to avoid:**
1. Specify Python version in pyproject.toml and enforce it across all environments
2. Never manually edit poetry.lock
3. Always use `poetry lock --no-update` to regenerate without unintended upgrades
4. Test in CI with the exact Python version as production

**Warning signs:**
- `poetry install` fails with "hash mismatch"
- Local works, CI fails
- Lock file shows different hashes on different machines

**Preventive code (pyproject.toml):**
```toml
[tool.poetry]
name = "agent-deploy"
version = "0.1.0"
python = "^3.11"  # Enforce Python 3.11+

[tool.poetry.dependencies]
python = "^3.11"  # Must match above

# CI / GitHub Actions
# ...
- name: Set up Python
  uses: actions/setup-python@v4
  with:
    python-version: "3.11"  # Must match pyproject.toml
```

---

## Code Examples

### PostgreSQL Schema Initialization (Verified Pattern)

```python
# migrations/versions/001_init_schema.py
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    # Create ENUM type for task status
    op.execute("""
        CREATE TYPE task_status AS ENUM (
            'pending', 'approved', 'executing', 'completed', 'failed', 'rejected'
        )
    """)

    # Tasks table: what was requested
    op.create_table(
        'tasks',
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('request_text', sa.Text, nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'approved', 'executing',
                  'completed', 'failed', 'rejected', name='task_status'),
                  default='pending', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('estimated_resources', postgresql.JSONB, nullable=True),
        sa.Column('actual_resources', postgresql.JSONB, nullable=True),
        sa.Column('external_ai_used', postgresql.JSONB, nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
    )

    # Execution logs table: what happened step-by-step
    op.create_table(
        'execution_logs',
        sa.Column('log_id', postgresql.UUID(as_uuid=True),
                  server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tasks.task_id', ondelete='CASCADE'), nullable=False),
        sa.Column('step_number', sa.Integer, nullable=False),
        sa.Column('agent_type', sa.String(50), nullable=False),
        sa.Column('action', sa.Text, nullable=False),
        sa.Column('status', sa.String(50), nullable=False),  # running, completed, failed
        sa.Column('output_summary', postgresql.JSONB, nullable=True),  # First 500 chars
        sa.Column('timestamp', sa.DateTime(timezone=True),
                  server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('duration_ms', sa.Integer, nullable=True),
    )

    # Separate large output storage (avoids TOAST performance cliff)
    op.create_table(
        'execution_output',
        sa.Column('output_id', postgresql.UUID(as_uuid=True),
                  server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('log_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('execution_logs.log_id', ondelete='CASCADE'), nullable=False),
        sa.Column('output_full', sa.Text, nullable=True),  # Raw text, not JSONB
        sa.Column('output_size_bytes', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('CURRENT_TIMESTAMP')),
    )

    # Indexes for post-mortem queries
    op.create_index('ix_tasks_created_at', 'tasks', ['created_at'])
    op.create_index('ix_tasks_status', 'tasks', ['status'])
    op.create_index('ix_execution_logs_task_id', 'execution_logs', ['task_id'])
    op.create_index('ix_execution_logs_agent_type', 'execution_logs', ['agent_type'])
    op.create_index('ix_execution_output_log_id', 'execution_output', ['log_id'])

def downgrade():
    op.drop_index('ix_execution_output_log_id', 'execution_output')
    op.drop_index('ix_execution_logs_agent_type', 'execution_logs')
    op.drop_index('ix_execution_logs_task_id', 'execution_logs')
    op.drop_index('ix_tasks_status', 'tasks')
    op.drop_index('ix_tasks_created_at', 'tasks')
    op.drop_table('execution_output')
    op.drop_table('execution_logs')
    op.drop_table('tasks')
    op.execute('DROP TYPE task_status')
```

### Pydantic Schema + Protocol Validation

```python
# src/common/schemas.py (Source: Pydantic v2 best practices)
from pydantic import BaseModel, Field, field_validator
from typing import Any, Literal
from uuid import UUID
from datetime import datetime

class MessageEnvelope(BaseModel):
    """Base message envelope for all protocol v1.0 messages."""
    protocol_version: str = Field(default="1.0")
    message_id: UUID
    from_agent: Literal["orchestrator", "infra", "desktop", "code", "research"]
    to_agent: Literal["orchestrator", "infra", "desktop", "code", "research"]
    timestamp: str  # ISO 8601
    trace_id: UUID  # For correlating related messages
    request_id: UUID  # For idempotency: duplicate requests return cached result
    type: Literal["work_request", "work_status", "work_result", "error"]
    payload: dict[str, Any]
    x_custom_fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator('protocol_version')
    @classmethod
    def validate_version(cls, v):
        if v != "1.0":
            raise ValueError(f"Unsupported protocol version: {v}")
        return v

class WorkRequest(MessageEnvelope):
    """Orchestrator → Agent: do this work."""
    type: Literal["work_request"]
    payload: dict = Field(...)

    @field_validator('payload')
    @classmethod
    def validate_payload(cls, v):
        required = {'task_id', 'work_type', 'parameters', 'hints'}
        missing = required - set(v.keys())
        if missing:
            raise ValueError(f"Missing required fields in payload: {missing}")
        return v

class WorkResult(MessageEnvelope):
    """Agent → Orchestrator: here's what happened."""
    type: Literal["work_result"]
    payload: dict = Field(...)

    @field_validator('payload')
    @classmethod
    def validate_payload(cls, v):
        required = {'task_id', 'status', 'exit_code'}
        missing = required - set(v.keys())
        if missing:
            raise ValueError(f"Missing required fields in payload: {missing}")
        return v

class ErrorMessage(MessageEnvelope):
    """Either direction: something went wrong."""
    type: Literal["error"]
    payload: dict = Field(...)

    @field_validator('payload')
    @classmethod
    def validate_payload(cls, v):
        required = {'error_code', 'error_message'}
        missing = required - set(v.keys())
        if missing:
            raise ValueError(f"Missing required fields in payload: {missing}")
        return v
```

### Docker Compose with Health Checks (Verified Pattern)

```yaml
# docker-compose.yml
version: '3.8'

services:
  postgres:
    image: postgres:15
    container_name: agent_deploy_postgres
    environment:
      POSTGRES_DB: agent_deploy
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres_local
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "postgres", "-d", "agent_deploy"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  rabbitmq:
    image: rabbitmq:3.12-management
    container_name: agent_deploy_rabbitmq
    environment:
      RABBITMQ_DEFAULT_USER: guest
      RABBITMQ_DEFAULT_PASS: guest
      RABBITMQ_DEFAULT_VHOST: /
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 15s
    ports:
      - "5672:5672"
      - "15672:15672"
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq

  ollama:
    image: ollama/ollama:latest
    container_name: agent_deploy_ollama
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
    ports:
      - "11434:11434"
    volumes:
      - ollama_models:/root/.ollama

  litellm:
    image: ghcr.io/berriai/litellm:latest
    container_name: agent_deploy_litellm
    depends_on:
      ollama:
        condition: service_healthy
    environment:
      OLLAMA_API_BASE: "http://ollama:11434"
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 10s

  orchestrator:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: agent_deploy_orchestrator
    depends_on:
      postgres:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
      litellm:
        condition: service_healthy
    environment:
      DATABASE_URL: "postgresql://postgres:postgres_local@postgres:5432/agent_deploy"
      RABBITMQ_URL: "amqp://guest:guest@rabbitmq:5672/"
      LITELLM_API_URL: "http://litellm:8000"
    ports:
      - "8001:8001"
    volumes:
      - .:/app

volumes:
  postgres_data:
  rabbitmq_data:
  ollama_models:
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual bash wait-for-it scripts in docker-compose | Native `healthcheck` + `depends_on: {condition: service_healthy}` | Docker 20.10 (2021) | Eliminates race conditions, declarative startup order |
| Database migrations as raw SQL files | Alembic with Python + SQLAlchemy ORM | 2015+ | Version control, reversibility, IDE integration |
| Vendor-specific LLM client libraries | Unified proxy layer (LiteLLM) | 2023-2024 | Vendor agnostic, cost tracking, fallback chains |
| Environment variables scattered in .env | .env.example in git + .env.local in .gitignore | 2020+ | Clear documentation, no accidental secret commits |
| Synchronous RabbitMQ clients | Async AMQP with pika + asyncio | 2023+ | Better scaling, reduced latency, cleaner code |
| Pytest without database fixtures | pytest-postgresql with automatic isolation | 2020+ | Fast, clean, deterministic tests |
| Raw JSON logging | Structured JSON logging with traceable IDs | 2022+ | Queryable logs, correlation across services |

**Deprecated/outdated:**
- **Flask-SQLAlchemy for new projects:** SQLAlchemy 2.0+ recommended; plain SQLAlchemy + async is more flexible
- **pgAudit extension for application-level auditing:** Modern apps use PostgreSQL triggers + audit tables; pgAudit is system-level
- **Manual retry logic in agents:** Use circuit breakers + idempotency tokens; Pika + RabbitMQ handle most cases
- **Ollama on CPU:** For production, consider quantized models (Q4_0) or batching; but Phase 1 is local dev, so standard Ollama is fine

---

## Open Questions

1. **Ollama Performance for Real Workloads**
   - What we know: Ollama neural-chat runs locally with zero cost; can respond in 1-5 seconds for medium prompts
   - What's unclear: Will it be fast enough for real-time planning? May need to fall back to Claude more often than anticipated
   - Recommendation: Phase 1 includes benchmarking task: send same prompt to Ollama + Claude, measure latency + cost. Use results to tune fallback thresholds

2. **JSONB Column Sizing in Execution Logs**
   - What we know: JSONB >2KB hits TOAST performance cliff
   - What's unclear: How large will typical agent outputs be? (Ansible playbook run could be 5MB of logs)
   - Recommendation: Implement `output_size_bytes` column in execution_output table; monitor in Phase 1. If outputs consistently >2KB, move to separate table (already designed in schema)

3. **RabbitMQ Message Ordering Guarantees**
   - What we know: RabbitMQ doesn't guarantee order across multiple consumers
   - What's unclear: Is message ordering needed for task execution steps? Or can steps be out-of-order?
   - Recommendation: Design agent protocol to support out-of-order step delivery (use step_number in logs, not arrival order). If ordering required, add single consumer per task_id

4. **Poetry + CI/CD Lock File Consistency**
   - What we know: Lock file hashes must match across Python versions
   - What's unclear: How to validate hash consistency in CI without running full install?
   - Recommendation: Phase 1 CI includes `poetry lock --check` to verify lock file is up-to-date with pyproject.toml

5. **LiteLLM Vendor Credential Rotation**
   - What we know: Phase 1 uses static API keys in config.json
   - What's unclear: How to rotate credentials without downtime?
   - Recommendation: Phase 1 defers this; Phase 2 could integrate Ansible vault or environment variable injection at runtime

---

## Sources

### Primary (HIGH confidence)

- **Alembic 1.18 Documentation** — [Auto Generating Migrations](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
- **Docker Compose Official Documentation** — [Control Startup Order](https://docs.docker.com/compose/how-tos/startup-order/)
- **PostgreSQL 15 Official Docs** — TOAST, JSONB indexing, constraints
- **SQLAlchemy 2.0 Documentation** — Connection pooling, QueuePool configuration
- **Pydantic v2 Documentation** — Field validation, model serialization
- **pytest-postgresql on PyPI** — Database fixture isolation patterns

### Secondary (MEDIUM confidence)

- [Let's Build Production-Ready Audit Logs in PostgreSQL](https://medium.com/@sehban.alam/lets-build-production-ready-audit-logs-in-postgresql-7125481713d8) — Dec 2025, Medium
- [Best Practices for Alembic and SQLAlchemy](https://medium.com/@pavel.loginov.dev/best-practices-for-alembic-and-sqlalchemy-73e4c8a6c205) — Pavel Loginov, Medium
- [Multi-Agent System Reliability: Failure Patterns and Root Causes](https://www.getmaxim.ai/articles/multi-agent-system-reliability-failure-patterns-root-causes-and-production-validation-strategies) — Maxim, 2026
- [LiteLLM Cost Tracking: Multi-Model Expense Management](https://www.statsig.com/perspectives/litellm-cost-tracking) — Statsig, 2025
- [Python Packaging Best Practices: Poetry in 2026](https://dasroot.net/posts/2026/01/python-packaging-best-practices-setuptools-poetry-hatch/) — Jan 2026
- [PostgreSQL JSONB TOAST Performance](https://pganalyze.com/blog/5mins-postgres-jsonb-toast) — pganalyze, 2025

### Tertiary (LOW confidence, WebSearch only)

- [The Agentic Mesh: Agent-to-Agent Communication Protocols](https://thinhdanggroup.github.io/agent-to-agent/) — Community resource
- [Top LLM Gateways 2025](https://agenta.ai/blog/top-llm-gateways) — Agenta blog
- Various Stack Overflow discussions on RabbitMQ + Pika reliability (not cited individually)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Verified with official docs (PostgreSQL, Docker, Alembic, SQLAlchemy, pytest-postgresql all current)
- Architecture patterns: HIGH — Docker health checks, Alembic migrations, Pydantic validation all verified with official sources
- PostgreSQL schema & JSONB: HIGH — PostgreSQL docs + 2025-2026 community posts confirm TOAST performance cliff
- LiteLLM fallback routing: MEDIUM — Official docs + 2025 blog posts confirm model registration requirement, but cost tracking limitations noted in community
- Pika / RabbitMQ reliability: MEDIUM — Official tutorials + 2025-2026 posts confirm patterns but Pika recovery is application-level
- Ollama performance: LOW — No official benchmarks for Phase 1 use cases; recommend Phase 1 testing

**Research date:** 2026-01-19
**Valid until:** 2026-02-19 (30 days; PostgreSQL stable, Alembic mature; LiteLLM updates quarterly)
**Refresh trigger:** If Ollama benchmarks reveal unexpected slowness, or if LiteLLM major version updates (>2.0)

---

## Implementation Readiness

All research findings are actionable and directly inform Phase 1 planning:

- ✓ Alembic workflow includes manual migration review step
- ✓ Docker Compose startup uses health checks + service_healthy conditions
- ✓ Protocol implementation requires explicit request_id idempotency
- ✓ SQLAlchemy pooling configured with pool_pre_ping=True
- ✓ PostgreSQL schema splits large outputs to separate table (avoids JSONB TOAST cliff)
- ✓ Poetry lock file locked in git; pyproject.toml specifies Python 3.11+
- ✓ LiteLLM config validates all fallback models are in model_list
- ✓ Testing uses pytest-postgresql for isolated databases

**Planner can proceed with Phase 1 planning.**
