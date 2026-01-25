"""Add audit columns to tasks table and immutability trigger.

Revision ID: 004
Revises: 003
Create Date: 2026-01-20

This migration adds audit tracking capabilities:
- services_touched: ARRAY column for tracking which services a task touched
- outcome: JSONB column for execution results (success/error, output summary)
- suggestions: JSONB column for post-mortem scaffolding (v2 feature)
- GIN index on services_touched for efficient containment queries
- Composite index on (status, created_at) for audit time-range queries
- Append-only trigger preventing UPDATE on completed tasks and DELETE on all tasks
- pause_queue table for persisting paused work that survives orchestrator restart
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, Sequence[str], None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add audit columns, indexes, trigger, and pause_queue table."""
    # 1. Add audit columns to tasks table
    op.add_column(
        "tasks",
        sa.Column("services_touched", postgresql.ARRAY(sa.TEXT()), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("outcome", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("suggestions", postgresql.JSONB(), nullable=True),
    )

    # 2. Create GIN index on services_touched for efficient containment queries
    op.create_index(
        "idx_tasks_services_touched",
        "tasks",
        ["services_touched"],
        postgresql_using="gin",
    )

    # 3. Create composite index on (status, created_at) for audit time-range queries
    op.execute(
        "CREATE INDEX idx_tasks_status_created_at ON tasks (status, created_at DESC)"
    )

    # 4. Create append-only trigger function
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_task_modification()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                -- Allow status transitions for non-completed tasks
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

    # 5. Attach trigger to tasks table
    op.execute("""
        CREATE TRIGGER enforce_task_immutability
        BEFORE UPDATE OR DELETE ON tasks
        FOR EACH ROW
        EXECUTE FUNCTION prevent_task_modification();
    """)

    # 6. Create pause_queue table for persisting paused work
    op.create_table(
        "pause_queue",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.task_id"),
            nullable=False,
        ),
        sa.Column("work_plan_json", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("paused_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("resume_after", sa.DateTime(), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="3"),
    )

    # 7. Create index on pause_queue for resume queries (resume_after, priority)
    op.create_index(
        "idx_pause_queue_resume",
        "pause_queue",
        ["resume_after", "priority"],
    )


def downgrade() -> None:
    """Downgrade schema: remove audit columns, indexes, trigger, and pause_queue table."""
    # Drop pause_queue table (includes index)
    op.drop_index("idx_pause_queue_resume", table_name="pause_queue")
    op.drop_table("pause_queue")

    # Drop trigger
    op.execute("DROP TRIGGER IF EXISTS enforce_task_immutability ON tasks")

    # Drop trigger function
    op.execute("DROP FUNCTION IF EXISTS prevent_task_modification()")

    # Drop composite index
    op.drop_index("idx_tasks_status_created_at", table_name="tasks")

    # Drop GIN index
    op.drop_index("idx_tasks_services_touched", table_name="tasks")

    # Drop columns (in reverse order of creation)
    op.drop_column("tasks", "suggestions")
    op.drop_column("tasks", "outcome")
    op.drop_column("tasks", "services_touched")
