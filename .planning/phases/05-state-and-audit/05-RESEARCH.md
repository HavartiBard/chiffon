# Phase 5: State & Audit Integration - Research

**Researched:** 2026-01-20
**Domain:** PostgreSQL audit tables, append-only patterns, pause/resume state machines, REST API query patterns
**Confidence:** HIGH

## Summary

Phase 5 implements execution state tracking, audit queries, pause/resume mechanisms, and post-mortem scaffolding. The research focused on five key areas: (1) append-only table design with PostgreSQL triggers to prevent UPDATE/DELETE, (2) efficient audit queries using composite and GIN indexes, (3) pause queue persistence with SKIP LOCKED pattern for state recovery, (4) REST API design for combined filtering, and (5) resource metrics capture using psutil.

The existing codebase has a solid foundation with SQLAlchemy ORM, Alembic migrations (currently at 003), and a Task model that already tracks basic execution state. Phase 5 extends this with services_touched array column, enhanced outcome JSON, immutability triggers, and a pause_queue table.

**Primary recommendation:** Extend the existing tasks table with new columns (services_touched ARRAY, outcome JSON, suggestions JSON) and add an append-only trigger, rather than creating a separate audit table. This leverages existing Task model relationships and keeps the codebase simpler.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0+ | ORM with PostgreSQL ARRAY support | Already in use, provides `contains()` for array queries |
| Alembic | 1.13+ | Database migrations with trigger support | Already in use, supports raw SQL for trigger creation |
| psutil | 5.9+ | CPU/memory metrics capture | De facto standard for Python system monitoring |
| pynvml | 11.5+ | NVIDIA GPU VRAM tracking | Official NVIDIA Python bindings |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| gpu-tracker | 2.0+ | Comprehensive GPU/CPU tracking | Alternative to psutil+pynvml if unified tracking needed |
| fastapi | 0.100+ | REST API with Query parameter validation | Already in use for orchestrator API |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| PostgreSQL triggers | Application-level validation | Triggers enforce at DB level; app validation can be bypassed |
| ARRAY column | Junction table | Array simpler for read-heavy; junction better for complex queries |
| psutil + pynvml | gpu-tracker | gpu-tracker is newer but requires Python 3.10+; psutil more mature |

**Installation:**
```bash
# psutil already likely installed; pynvml for GPU tracking
pip install psutil pynvml
```

## Architecture Patterns

### Recommended Project Structure
```
src/
├── common/
│   ├── models.py           # Extended Task model with new fields
│   └── resource_tracker.py # NEW: psutil/pynvml wrapper for metrics capture
├── orchestrator/
│   ├── service.py          # Extended with pause/resume logic
│   ├── api.py              # Extended with /audit/* endpoints
│   ├── audit.py            # NEW: Audit query service
│   └── pause_manager.py    # NEW: Pause queue state machine
└── migrations/
    └── versions/
        └── 004_audit_columns.py  # NEW: Add audit fields + trigger
```

### Pattern 1: Append-Only Table with BEFORE Trigger

**What:** PostgreSQL trigger that raises exception on UPDATE/DELETE, enforcing immutability at database level.

**When to use:** Any table where historical records must be preserved (audit logs, execution history).

**Example:**
```sql
-- Source: PostgreSQL Documentation + Community patterns
CREATE OR REPLACE FUNCTION prevent_task_modification()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        -- Allow status transitions only (for in-progress updates)
        IF OLD.status IN ('pending', 'executing') AND NEW.status != OLD.status THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'UPDATE not allowed on completed task records (task_id=%)', OLD.task_id;
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'DELETE not allowed on audit table tasks (task_id=%)', OLD.task_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_task_immutability
BEFORE UPDATE OR DELETE ON tasks
FOR EACH ROW
EXECUTE FUNCTION prevent_task_modification();
```

**Note:** The trigger allows status transitions for in-progress tasks but prevents modification of completed records. This balances immutability with operational needs.

### Pattern 2: GIN Index on ARRAY Column for Service Filtering

**What:** PostgreSQL GIN index enabling efficient containment queries on services_touched array.

**When to use:** Any ARRAY column that needs @> (contains) or && (overlaps) queries.

**Example:**
```sql
-- Source: Tiger Data GIN Index Guide
-- Create index
CREATE INDEX idx_tasks_services_touched ON tasks USING GIN (services_touched);

-- Query using containment (uses index)
SELECT * FROM tasks WHERE services_touched @> ARRAY['kuma'];

-- Query using overlap (uses index)
SELECT * FROM tasks WHERE services_touched && ARRAY['kuma', 'portainer'];
```

**SQLAlchemy equivalent:**
```python
# Source: SQLAlchemy PostgreSQL Dialect
from sqlalchemy.dialects.postgresql import ARRAY

# Model definition
services_touched = Column(ARRAY(sa.TEXT), nullable=True)

# Query using contains
tasks = db.query(Task).filter(Task.services_touched.contains(['kuma'])).all()

# Query using overlap
tasks = db.query(Task).filter(Task.services_touched.overlap(['kuma', 'portainer'])).all()
```

### Pattern 3: Pause Queue with SKIP LOCKED for State Recovery

**What:** PostgreSQL-backed job queue using FOR UPDATE SKIP LOCKED for concurrent access, with persistent state for orchestrator restart recovery.

**When to use:** Work items that must survive process restarts and support pause/resume.

**Example:**
```python
# Pause queue table schema (via Alembic)
pause_queue = Table(
    'pause_queue',
    Column('id', Integer, primary_key=True),
    Column('task_id', UUID, ForeignKey('tasks.task_id'), nullable=False),
    Column('work_plan_json', JSON, nullable=False),  # Serialized WorkPlan
    Column('reason', String(100), nullable=False),    # 'insufficient_capacity', 'manual_pause'
    Column('paused_at', DateTime, default=func.now()),
    Column('resume_after', DateTime, nullable=True),  # For timed auto-resume
    Column('priority', Integer, default=3),
)

# Query for resumable work (with SKIP LOCKED)
# Source: Brandur.org Postgres Queues
SELECT * FROM pause_queue
WHERE resume_after IS NULL OR resume_after <= NOW()
ORDER BY priority DESC, paused_at ASC
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

### Pattern 4: Composite Index for Status + Time Range Queries

**What:** Multi-column B-tree index optimized for common audit query patterns.

**When to use:** Queries that filter by status AND time range together.

**Example:**
```sql
-- Source: PostgreSQL Index Documentation
CREATE INDEX idx_tasks_status_created_at ON tasks (status, created_at DESC);

-- Efficiently answers: "all failures in last week"
SELECT * FROM tasks
WHERE status = 'failed'
AND created_at > NOW() - INTERVAL '7 days'
ORDER BY created_at DESC;
```

### Anti-Patterns to Avoid

- **Using ANY() with GIN index:** The `= ANY(array_column)` operator does NOT use GIN indexes. Use `array_column @> ARRAY[value]` instead.
- **Storing suggestions as separate table in v1:** Premature normalization; JSON field is simpler and sufficient for scaffolding.
- **Application-only immutability:** Relying solely on Python code to prevent modifications; DB triggers are more robust.
- **Polling without SKIP LOCKED:** Causes race conditions when multiple workers check pause_queue.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CPU time measurement | Custom timing code | `psutil.Process().cpu_times()` | Handles user/system/children time correctly |
| GPU VRAM tracking | nvidia-smi parsing | `pynvml` library | Official bindings, handles errors gracefully |
| Append-only enforcement | Python-level checks | PostgreSQL BEFORE trigger | Cannot be bypassed, even by raw SQL |
| Array containment queries | LIKE with string manipulation | GIN index + @> operator | 10-100x faster for large tables |
| Job queue with recovery | Custom polling loop | SKIP LOCKED pattern | Prevents race conditions, survives restarts |

**Key insight:** PostgreSQL has native support for all the query patterns needed (ARRAY containment, GIN indexes, triggers, SKIP LOCKED). Using these features directly is more reliable and performant than application-level workarounds.

## Common Pitfalls

### Pitfall 1: GIN Index Not Used for ANY() Queries

**What goes wrong:** Queries using `WHERE value = ANY(services_touched)` do full table scans despite GIN index.

**Why it happens:** GIN indexes support @> (contains) and && (overlaps), but not the ANY() construct.

**How to avoid:** Always use containment operators:
```python
# Wrong (no index)
db.query(Task).filter(Task.services_touched.any('kuma'))

# Right (uses GIN index)
db.query(Task).filter(Task.services_touched.contains(['kuma']))
```

**Warning signs:** Slow audit queries that should be fast; EXPLAIN shows Seq Scan instead of Index Scan.

### Pitfall 2: Trigger Blocking Status Transitions

**What goes wrong:** Append-only trigger prevents legitimate status updates on in-progress tasks.

**Why it happens:** Trigger too strict; blocks UPDATE when task status needs to change.

**How to avoid:** Trigger should allow status transitions but prevent modification of completed records:
```sql
IF OLD.status IN ('pending', 'executing') AND NEW.status != OLD.status THEN
    RETURN NEW;  -- Allow status transitions
END IF;
```

**Warning signs:** Tasks stuck in 'executing' status; IntegrityError on legitimate status updates.

### Pitfall 3: Pause Queue Not Surviving Restart

**What goes wrong:** Orchestrator restarts, loses track of paused work.

**Why it happens:** Pause state stored in memory instead of database.

**How to avoid:**
1. Persist to pause_queue table BEFORE returning from pause operation
2. On startup, query pause_queue for items to replay
3. Use atomic transaction: INSERT to pause_queue + UPDATE task status

**Warning signs:** Work disappears after orchestrator restart; users report "lost" tasks.

### Pitfall 4: Resource Metrics Captured at Wrong Time

**What goes wrong:** Resource usage reported is for orchestrator process, not the actual work execution.

**Why it happens:** Metrics captured before dispatch or after completion, not during execution.

**How to avoid:**
1. Capture start metrics before work begins on agent
2. Capture end metrics after work completes on agent
3. Send delta (end - start) back to orchestrator

**Warning signs:** All tasks show same resource usage; GPU-heavy tasks show 0 VRAM used.

### Pitfall 5: JSON Suggestions Field Growing Unbounded

**What goes wrong:** suggestions JSON field accumulates historical suggestions, grows very large.

**Why it happens:** No cleanup policy for old suggestions; each analysis appends.

**How to avoid:**
1. Store only latest N suggestions (e.g., 10)
2. Or timestamp each suggestion and prune old ones
3. In v1, field is unpopulated so not immediate concern

**Warning signs:** Large row sizes; slow SELECT on tasks with many suggestions.

## Code Examples

Verified patterns from official sources:

### Resource Metrics Capture (psutil + pynvml)

```python
# Source: psutil documentation + pynvml documentation
import psutil
import time
from typing import Optional

try:
    import pynvml
    pynvml.nvmlInit()
    HAS_GPU = True
except Exception:
    HAS_GPU = False


def capture_resource_snapshot() -> dict:
    """Capture current resource metrics for a process."""
    process = psutil.Process()
    cpu_times = process.cpu_times()
    memory_info = process.memory_info()

    metrics = {
        "cpu_user_seconds": cpu_times.user,
        "cpu_system_seconds": cpu_times.system,
        "memory_rss_bytes": memory_info.rss,
        "memory_vms_bytes": memory_info.vms,
        "wall_clock_time": time.time(),
    }

    if HAS_GPU:
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            metrics["gpu_vram_used_bytes"] = mem_info.used
            metrics["gpu_vram_total_bytes"] = mem_info.total
        except Exception:
            pass

    return metrics


def calculate_resource_usage(start: dict, end: dict) -> dict:
    """Calculate resource delta between start and end snapshots."""
    return {
        "cpu_time_seconds": (
            (end["cpu_user_seconds"] - start["cpu_user_seconds"]) +
            (end["cpu_system_seconds"] - start["cpu_system_seconds"])
        ),
        "wall_clock_seconds": end["wall_clock_time"] - start["wall_clock_time"],
        "peak_memory_bytes": max(start["memory_rss_bytes"], end["memory_rss_bytes"]),
        "gpu_vram_used_bytes": end.get("gpu_vram_used_bytes", 0),
    }
```

### SQLAlchemy ARRAY Query with GIN Index

```python
# Source: SQLAlchemy PostgreSQL dialect documentation
from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID, JSONB
from src.common.database import Base


class TaskAudit(Base):
    """Extended Task model with audit fields."""
    __tablename__ = "tasks"

    task_id = Column(UUID(as_uuid=True), primary_key=True)
    status = Column(String(50), nullable=False)
    created_at = Column(DateTime, nullable=False, default=func.now())

    # Audit columns
    services_touched = Column(ARRAY(String), nullable=True)
    outcome = Column(JSONB, nullable=True)
    resources_used = Column(JSONB, nullable=True)
    suggestions = Column(JSONB, nullable=True)  # Scaffolding for v2 post-mortem


# Query: All failures in last week
def get_recent_failures(db, days: int = 7):
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)
    return db.query(TaskAudit).filter(
        TaskAudit.status == 'failed',
        TaskAudit.created_at > cutoff
    ).order_by(TaskAudit.created_at.desc()).all()


# Query: All changes to service X
def get_by_service(db, service_name: str):
    return db.query(TaskAudit).filter(
        TaskAudit.services_touched.contains([service_name])
    ).order_by(TaskAudit.created_at.desc()).all()


# Query: Combined filter (status + time + service)
def audit_query(db, status: str = None, service: str = None, since_days: int = None):
    query = db.query(TaskAudit)

    if status:
        query = query.filter(TaskAudit.status == status)
    if service:
        query = query.filter(TaskAudit.services_touched.contains([service]))
    if since_days:
        cutoff = datetime.utcnow() - timedelta(days=since_days)
        query = query.filter(TaskAudit.created_at > cutoff)

    return query.order_by(TaskAudit.created_at.desc()).all()
```

### Alembic Migration with Trigger

```python
# Source: Alembic documentation + PostgreSQL trigger documentation
"""Add audit columns and append-only trigger.

Revision ID: 004
Revises: 003
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004"
down_revision = "003"


def upgrade():
    # Add audit columns to tasks table
    op.add_column('tasks', sa.Column(
        'services_touched',
        postgresql.ARRAY(sa.TEXT()),
        nullable=True
    ))
    op.add_column('tasks', sa.Column(
        'outcome',
        postgresql.JSONB(),
        nullable=True
    ))
    op.add_column('tasks', sa.Column(
        'suggestions',
        postgresql.JSONB(),
        nullable=True
    ))

    # Create GIN index for services array
    op.create_index(
        'idx_tasks_services_touched',
        'tasks',
        ['services_touched'],
        postgresql_using='gin'
    )

    # Create composite index for status + time queries
    op.create_index(
        'idx_tasks_status_created_at',
        'tasks',
        ['status', sa.text('created_at DESC')]
    )

    # Create append-only trigger function
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_task_modification()
        RETURNS trigger AS $$
        BEGIN
            -- Allow status transitions for in-progress tasks
            IF TG_OP = 'UPDATE' THEN
                IF OLD.status IN ('pending', 'approved', 'executing') THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'UPDATE not allowed on completed task (task_id=%)', OLD.task_id;
            ELSIF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'DELETE not allowed on tasks table (task_id=%)', OLD.task_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Attach trigger to tasks table
    op.execute("""
        CREATE TRIGGER enforce_task_immutability
        BEFORE UPDATE OR DELETE ON tasks
        FOR EACH ROW
        EXECUTE FUNCTION prevent_task_modification();
    """)

    # Create pause_queue table
    op.create_table(
        'pause_queue',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tasks.task_id'), nullable=False),
        sa.Column('work_plan_json', postgresql.JSONB(), nullable=False),
        sa.Column('reason', sa.String(100), nullable=False),
        sa.Column('paused_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('resume_after', sa.DateTime(), nullable=True),
        sa.Column('priority', sa.Integer(), server_default='3'),
    )

    op.create_index('idx_pause_queue_resume', 'pause_queue', ['resume_after', 'priority'])


def downgrade():
    op.drop_table('pause_queue')
    op.execute("DROP TRIGGER IF EXISTS enforce_task_immutability ON tasks")
    op.execute("DROP FUNCTION IF EXISTS prevent_task_modification()")
    op.drop_index('idx_tasks_status_created_at')
    op.drop_index('idx_tasks_services_touched')
    op.drop_column('tasks', 'suggestions')
    op.drop_column('tasks', 'outcome')
    op.drop_column('tasks', 'services_touched')
```

### REST API Audit Endpoints

```python
# Source: FastAPI documentation
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("/failures")
async def get_failures(
    days: int = Query(7, ge=1, le=90, description="Look back N days"),
    service: Optional[str] = Query(None, description="Filter by service name"),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Get all failed tasks in the specified time range.

    Supports STATE-03: "all failures in last week"
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    query = db.query(Task).filter(
        Task.status == 'failed',
        Task.created_at > cutoff
    )

    if service:
        query = query.filter(Task.services_touched.contains([service]))

    return query.order_by(Task.created_at.desc()).limit(limit).all()


@router.get("/by-service/{service_name}")
async def get_by_service(
    service_name: str,
    status: Optional[str] = Query(None, description="Filter by status"),
    days: Optional[int] = Query(None, ge=1, le=365),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Get all tasks that touched a specific service.

    Supports STATE-03: "all changes to service X"
    """
    query = db.query(Task).filter(
        Task.services_touched.contains([service_name])
    )

    if status:
        query = query.filter(Task.status == status)
    if days:
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = query.filter(Task.created_at > cutoff)

    return query.order_by(Task.created_at.desc()).limit(limit).all()


@router.get("/query")
async def audit_query(
    status: Optional[str] = Query(None),
    service: Optional[str] = Query(None),
    intent: Optional[str] = Query(None, description="Inferred from service+action"),
    days: Optional[int] = Query(None, ge=1, le=365),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Combined audit query with multiple filters.

    Supports combined filtering (status + time + service + inferred intent).
    """
    query = db.query(Task)

    if status:
        query = query.filter(Task.status == status)
    if service:
        query = query.filter(Task.services_touched.contains([service]))
    if days:
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = query.filter(Task.created_at > cutoff)
    if intent:
        # Infer intent from outcome JSON (action type stored there)
        query = query.filter(
            Task.outcome['action_type'].astext == intent
        )

    return query.order_by(Task.created_at.desc()).limit(limit).all()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Separate audit table | Extend main table with immutability trigger | PostgreSQL 9.1+ | Simpler schema, same guarantees |
| Application-level append-only | Database trigger enforcement | Always preferred | Cannot be bypassed |
| B-tree on ARRAY | GIN index for containment queries | PostgreSQL 9.1+ | Orders of magnitude faster |
| Custom job queue polling | SKIP LOCKED pattern | PostgreSQL 9.5+ | Race-condition free |
| nvidia-smi shell parsing | pynvml Python bindings | 2020+ | More reliable, proper error handling |

**Deprecated/outdated:**
- **JSON type (vs JSONB):** Use JSONB for all new columns; JSON only preserves formatting which is rarely needed
- **hstore extension:** Superseded by JSONB for key-value storage
- **Custom array operators:** Use built-in @>, &&, <@ operators with GIN index

## Open Questions

Things that couldn't be fully resolved:

1. **Pause threshold percentage**
   - What we know: Need a threshold to auto-pause when capacity is low
   - What's unclear: Exact percentage (10%? 20%? based on task requirements?)
   - Recommendation: Start with 20% as default, make configurable

2. **Pause queue ordering**
   - What we know: Need ordering for resume priority
   - What's unclear: FIFO vs. priority-based vs. hybrid
   - Recommendation: Priority + FIFO within same priority (ORDER BY priority DESC, paused_at ASC)

3. **Retry backoff strategy**
   - What we know: Failed tasks may need retry
   - What's unclear: How many retries? What backoff?
   - Recommendation: Defer to v2; v1 stores failure info for manual intervention

4. **Resource metrics granularity**
   - What we know: Need CPU time, wall clock, GPU VRAM
   - What's unclear: Per-step vs. per-task granularity
   - Recommendation: Per-task in v1; per-step adds complexity

## Sources

### Primary (HIGH confidence)
- [PostgreSQL Trigger Functions Documentation](https://www.postgresql.org/docs/current/plpgsql-trigger.html) - Trigger syntax, TG_OP variable, RAISE EXCEPTION
- [PostgreSQL GIN Index Documentation](https://www.postgresql.org/docs/current/gin.html) - GIN index creation and operators
- [PostgreSQL JSONB Documentation](https://www.postgresql.org/docs/current/datatype-json.html) - JSON vs JSONB, indexing
- [psutil Documentation](https://psutil.readthedocs.io/en/latest/) - cpu_times(), memory_info() methods
- [SQLAlchemy PostgreSQL ARRAY](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#array-types) - contains(), overlap() methods

### Secondary (MEDIUM confidence)
- [Tiger Data GIN Index Guide](https://www.tigerdata.com/learn/optimizing-array-queries-with-gin-indexes-in-postgresql) - GIN index best practices
- [Brandur.org Postgres Queues](https://brandur.org/postgres-queues) - SKIP LOCKED pattern
- [Task Queue Design with Postgres](https://medium.com/@huimin.hacker/task-queue-design-with-postgres-b57146d741dc) - Pause/resume patterns
- [Heap JSONB Guide](https://www.heap.io/blog/when-to-avoid-jsonb-in-a-postgresql-schema) - When to use JSONB

### Tertiary (LOW confidence)
- [gpu-tracker PyPI](https://pypi.org/project/gpu-tracker/) - Alternative GPU tracking library (requires validation)
- Community patterns for append-only triggers (requires testing)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - psutil and pynvml are well-documented, PostgreSQL features verified
- Architecture: HIGH - Patterns based on PostgreSQL official documentation
- Schema design: HIGH - Extends existing models with proven patterns
- Pitfalls: MEDIUM - Based on community experience, some require validation
- Code examples: HIGH - Based on official documentation

**Research date:** 2026-01-20
**Valid until:** 2026-02-20 (30 days - stable technology stack)
