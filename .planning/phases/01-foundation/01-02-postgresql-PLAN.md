---
phase: 01-foundation
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - migrations/env.py
  - migrations/versions/001_initial_schema.py
  - src/common/models.py
  - src/common/database.py
  - scripts/seed_sample_data.py
  - scripts/query_examples.sql
  - pyproject.toml
autonomous: true
user_setup: []

must_haves:
  truths:
    - "User can connect to PostgreSQL and query tasks table"
    - "Schema includes tasks and execution_logs tables with proper relationships"
    - "Indexes on created_at and task_id are present for query performance"
    - "Sample data loads and post-mortem queries return expected results"
    - "Schema versioning with Alembic migrations ready"
  artifacts:
    - path: "migrations/versions/001_initial_schema.py"
      provides: "Alembic migration creating tasks + execution_logs tables"
      contains: ["op.create_table", "task_id", "execution_logs"]
    - path: "src/common/models.py"
      provides: "SQLAlchemy ORM models for tasks and execution_logs"
      exports: ["Task", "ExecutionLog"]
    - path: "src/common/database.py"
      provides: "Database connection and session factory"
      contains: ["SessionLocal", "Base", "engine"]
    - path: "scripts/seed_sample_data.py"
      provides: "Sample data population for testing"
      contains: ["task_id", "status", "execution_logs"]
    - path: "scripts/query_examples.sql"
      provides: "Post-mortem query reference documentation"
      contains: ["failed tasks in last week", "execution timeline", "resource usage"]
  key_links:
    - from: "src/common/models.py"
      to: "src/common/database.py"
      via: "ORM model imports engine + Base"
      pattern: "from.*models import Task"
    - from: "migrations/versions/001_initial_schema.py"
      to: "docker-compose.yml"
      via: "Migration runs against postgres container"
      pattern: "DATABASE_URL"
    - from: "scripts/seed_sample_data.py"
      to: "src/common/models.py"
      via: "Seed creates Task + ExecutionLog instances"
      pattern: "Task\\(|ExecutionLog\\("
---

## Plan: PostgreSQL Schema, ORM Models, Alembic Migrations

**Goal:** PostgreSQL schema designed for operational state tracking and post-mortem analysis. ORM models defined. Alembic migrations ready. Sample data loads for testing.

**Deliverables:**
- PostgreSQL tables: tasks (task state), execution_logs (step-by-step execution)
- SQLAlchemy ORM models with relationships and validation
- Alembic migration framework (versions/ directory)
- Sample data script for testing queries
- Post-mortem query examples documented

**Success Criteria:**
- `poetry run alembic upgrade head` initializes schema
- `psql -d agent_deploy -c "SELECT * FROM tasks LIMIT 1"` returns schema (no data yet)
- `poetry run python scripts/seed_sample_data.py` populates sample tasks + logs
- Query "all failed tasks in last week" returns expected rows
- Indexes on created_at and task_id confirm with `\d+ tasks` in psql

### Tasks

<task type="auto">
  <name>Task 1: Define SQLAlchemy ORM models and database connection</name>
  <files>
    src/common/database.py
    src/common/models.py
  </files>
  <action>
    Create database connection layer and ORM model definitions:

    1. **src/common/database.py** - SQLAlchemy setup:
       - Import: from sqlalchemy import create_engine; from sqlalchemy.orm import sessionmaker, declarative_base
       - Load DATABASE_URL from config (default to postgresql://agent:password@localhost:5432/agent_deploy)
       - Create engine: create_engine(DATABASE_URL, echo=False for prod, True for debug)
       - Create session factory: SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
       - Create Base = declarative_base()
       - Export: engine, SessionLocal, Base (used by models.py and Alembic)

    2. **src/common/models.py** - SQLAlchemy ORM models:
       - Import Base from database.py
       - Define Task model:
         - task_id: UUID primary key (default=uuid4)
         - project_id: UUID nullable (for v2 multi-project)
         - request_text: TEXT
         - status: ENUM (pending|approved|executing|completed|failed|rejected)
         - created_at: DateTime (default=utcnow, indexed)
         - created_by: String nullable
         - approved_at: DateTime nullable
         - completed_at: DateTime nullable
         - estimated_resources: JSON (dict with duration_seconds, gpu_vram_mb, cpu_cores)
         - actual_resources: JSON (duration_seconds, gpu_vram_mb_used, cpu_time_ms, etc.)
         - external_ai_used: JSON (model, token_count, cost_usd per provider)
         - error_message: TEXT nullable
         - relationship: execution_logs = relationship("ExecutionLog", back_populates="task", cascade="all, delete-orphan")
         - __tablename__ = "tasks"

       - Define ExecutionLog model:
         - log_id: UUID primary key (default=uuid4)
         - task_id: UUID foreign key → Task.task_id
         - step_number: Integer
         - agent_type: ENUM (orchestrator|infra|desktop|code|research)
         - action: TEXT (description of what agent did)
         - status: ENUM (running|completed|failed)
         - output_summary: TEXT (first 500 chars)
         - output_full: JSON (full output or reference)
         - timestamp: DateTime (default=utcnow)
         - duration_ms: Integer
         - relationship: task = relationship("Task", back_populates="execution_logs")
         - __tablename__ = "execution_logs"

       - All models inherit from Base
       - Use proper imports: from sqlalchemy import Column, String, Integer, DateTime, JSON, UUID, Enum, ForeignKey, func
       - Add __repr__ for readable logging

    Ensure config.py is imported and DATABASE_URL is used.
  </action>
  <verify>
    - `python -c "from src.common.models import Task, ExecutionLog; from src.common.database import Base, engine; print('Imports OK')"` succeeds
    - `python -c "from src.common.database import SessionLocal; session = SessionLocal(); print('SessionLocal OK'); session.close()"` succeeds
    - No SQLAlchemy errors on import (all model definitions valid)
  </verify>
  <done>
    - Database connection layer ready
    - ORM models defined with proper relationships
    - Foreign key constraints defined (execution_logs → tasks)
    - Models ready for migration
  </done>
</task>

<task type="auto">
  <name>Task 2: Create Alembic migration framework and initial schema migration</name>
  <files>
    migrations/env.py
    migrations/script.py.mako
    migrations/versions/001_initial_schema.py
    migrations/alembic.ini
  </files>
  <action>
    Set up Alembic version control for database schema:

    1. **Initialize Alembic** (if not already done):
       - Run: `poetry run alembic init migrations` (creates structure)
       - This generates migrations/, alembic.ini, env.py, etc.

    2. **migrations/alembic.ini** - Configuration:
       - Set sqlalchemy.url = driver://user:password@localhost/dbname (load from env in env.py)
       - Ensure version_locations points to migrations/versions

    3. **migrations/env.py** - Alembic environment:
       - Configure to use SQLAlchemy's create_all pattern
       - Load config.DATABASE_URL from environment (not hardcoded in alembic.ini)
       - Set target_metadata = Base.metadata (from src.common.models import Base)
       - Implement offline migration support (for CI/CD)
       - Implement online migration support (for dev)

    4. **migrations/versions/001_initial_schema.py** - Initial migration:
       - Use Alembic op API: op.create_table, op.create_index, op.execute
       - Create tasks table:
         ```
         task_id: UUID PK
         project_id: UUID nullable
         request_text: TEXT not null
         status: VARCHAR(50) default 'pending'
         created_at: TIMESTAMP default now()
         created_by: VARCHAR(255) nullable
         approved_at: TIMESTAMP nullable
         completed_at: TIMESTAMP nullable
         estimated_resources: JSONB nullable
         actual_resources: JSONB nullable
         external_ai_used: JSONB nullable
         error_message: TEXT nullable
         ```
       - Create execution_logs table:
         ```
         log_id: UUID PK
         task_id: UUID FK → tasks.task_id
         step_number: INTEGER
         agent_type: VARCHAR(50)
         action: TEXT
         status: VARCHAR(50)
         output_summary: TEXT nullable
         output_full: JSONB nullable
         timestamp: TIMESTAMP default now()
         duration_ms: INTEGER
         ```
       - Create indexes:
         - tasks(created_at)
         - tasks(status)
         - execution_logs(task_id)
       - Write upgrade() and downgrade() functions
       - Add descriptive comment in file header

    5. **migrations/script.py.mako** - Template (generated):
       - Modify if needed for consistency (usually fine as-is)

    Test migration locally: `poetry run alembic current` and `poetry run alembic upgrade head`.
  </action>
  <verify>
    - `poetry run alembic current` shows no current revision (pre-upgrade)
    - `poetry run alembic upgrade head` completes without errors
    - `poetry run alembic current` shows "001_initial_schema"
    - `docker-compose exec postgres psql -U agent -d agent_deploy -c "\dt tasks execution_logs"` lists both tables
    - `docker-compose exec postgres psql -U agent -d agent_deploy -c "\d+ tasks"` shows all columns + indexes
  </verify>
  <done>
    - Alembic migration system ready
    - Initial schema migration created and tested
    - Tables created with proper relationships and indexing
    - Ready for seed data and queries
  </done>
</task>

<task type="auto">
  <name>Task 3: Create sample data script and post-mortem query examples</name>
  <files>
    scripts/seed_sample_data.py
    scripts/query_examples.sql
  </files>
  <action>
    Populate sample data for testing and document query patterns:

    1. **scripts/seed_sample_data.py** - Python script to populate sample data:
       - Import models from src.common.models, SessionLocal from src.common.database
       - Create 5-10 sample tasks with various statuses:
         - 2-3 completed tasks from "2 days ago"
         - 1-2 failed tasks from "3 days ago"
         - 1 executing task (current)
         - 1 pending task
       - For each task, create 3-5 execution log entries with realistic steps:
         - E.g., for deploy task: "Plan deployment" → "Download artifact" → "Deploy container" → "Verify service"
       - Sample values:
         - request_text: "Deploy Kuma to homelab", "Update DNS config", etc.
         - estimated_resources: {duration_seconds: 300, gpu_vram_mb: 2048, cpu_cores: 2}
         - actual_resources: {duration_seconds: 280, gpu_vram_mb_used: 1800, cpu_time_ms: 15000}
         - external_ai_used: {model: "claude-opus", token_count: 5000, cost_usd: 0.15}
       - Wrap in transaction: session.add_all(), session.commit(), then session.close()
       - Print summary: "Created X tasks with Y execution logs"

    2. **scripts/query_examples.sql** - Reference for post-mortem queries:
       - Document 5-6 useful queries with explanations:
         1. All failed tasks in last 7 days
            ```sql
            SELECT task_id, request_text, status, error_message, created_at
            FROM tasks
            WHERE status = 'failed' AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC;
            ```
         2. Execution timeline for a specific task
            ```sql
            SELECT task_id, step_number, agent_type, action, status, duration_ms, timestamp
            FROM execution_logs
            WHERE task_id = 'XXX'
            ORDER BY step_number;
            ```
         3. Total resources used by task
            ```sql
            SELECT task_id, request_text,
              (actual_resources->>'duration_seconds')::int as duration_sec,
              (actual_resources->>'gpu_vram_mb_used')::int as gpu_mb
            FROM tasks
            WHERE created_at > NOW() - INTERVAL '30 days'
            ORDER BY created_at DESC;
            ```
         4. Tasks using external AI
            ```sql
            SELECT task_id, request_text,
              external_ai_used->>'model' as model,
              (external_ai_used->>'cost_usd')::numeric as cost
            FROM tasks
            WHERE external_ai_used IS NOT NULL
            ORDER BY created_at DESC;
            ```
         5. Average duration by agent type
            ```sql
            SELECT agent_type, AVG(duration_ms) as avg_duration_ms, COUNT(*) as execution_count
            FROM execution_logs
            GROUP BY agent_type;
            ```
         6. Failed steps (errors during execution)
            ```sql
            SELECT task_id, step_number, action, status, output_summary
            FROM execution_logs
            WHERE status = 'failed'
            ORDER BY timestamp DESC;
            ```
       - Add header comment explaining usage: "Run these queries against agent_deploy database to analyze execution history"
  </action>
  <verify>
    - `poetry run python scripts/seed_sample_data.py` completes without errors
    - Check output contains "Created X tasks with Y execution logs"
    - `docker-compose exec postgres psql -U agent -d agent_deploy -c "SELECT COUNT(*) FROM tasks"` shows non-zero count (e.g., 5-10)
    - Run one query from query_examples.sql: `docker-compose exec postgres psql -U agent -d agent_deploy < scripts/query_examples.sql` (first query should return results)
    - Query "failed tasks in last week": `SELECT COUNT(*) FROM tasks WHERE status = 'failed' AND created_at > NOW() - INTERVAL '7 days'` shows >= 1
  </verify>
  <done>
    - Sample data loads successfully (5-10 tasks with execution logs)
    - Post-mortem queries tested and documented
    - Schema verified with realistic data
    - Ready for Phase 2 to use for testing
  </done>
</task>

</tasks>

<verification>
After all tasks complete:
1. `poetry run alembic upgrade head` — schema initialized
2. `poetry run python scripts/seed_sample_data.py` — sample data loaded
3. Query sample data:
   - `docker-compose exec postgres psql -U agent -d agent_deploy -c "SELECT COUNT(*) FROM tasks"` should show 5-10 tasks
   - `docker-compose exec postgres psql -U agent -d agent_deploy -c "SELECT COUNT(*) FROM execution_logs"` should show 15-50 logs
4. Run post-mortem queries from query_examples.sql and verify results
5. Verify indexing: `docker-compose exec postgres psql -U agent -d agent_deploy -c "SELECT schemaname, tablename, indexname FROM pg_indexes WHERE tablename IN ('tasks', 'execution_logs')"` shows indexes on created_at, status, task_id
</verification>

<success_criteria>
- PostgreSQL schema initialized with tasks and execution_logs tables
- ORM models ready for Phase 2 API endpoints
- Alembic migration framework allows future schema changes
- Sample data loads for testing post-mortem queries
- Indexes present for performance-critical queries
- Schema versioning ready in git (migrations/versions/)
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation/01-02-SUMMARY.md` with:
- Migration status: "alembic current" output
- Schema verification: table counts, column types confirmed
- Sample data loaded: task count, execution log count
- Query examples tested and working
</output>
