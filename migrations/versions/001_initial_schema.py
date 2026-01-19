"""Create initial schema for tasks and execution_logs.

Revision ID: 001
Revises:
Create Date: 2026-01-19

This migration creates the foundational tables for:
- tasks: tracking user requests and their execution state
- execution_logs: detailed step-by-step logs of agent actions
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: create tasks and execution_logs tables."""
    # Create tasks table
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("project_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("request_text", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("estimated_resources", sa.JSON(), nullable=True),
        sa.Column("actual_resources", sa.JSON(), nullable=True),
        sa.Column("external_ai_used", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
    )

    # Create indexes on tasks table for query performance
    op.create_index(
        "idx_tasks_created_at",
        "tasks",
        ["created_at"],
    )
    op.create_index(
        "idx_tasks_status",
        "tasks",
        ["status"],
    )

    # Create execution_logs table
    op.create_table(
        "execution_logs",
        sa.Column("log_id", sa.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("task_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("agent_type", sa.String(50), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("output_summary", sa.String(), nullable=True),
        sa.Column("output_full", sa.JSON(), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.task_id"],
            ondelete="CASCADE",
        ),
    )

    # Create indexes on execution_logs table
    op.create_index(
        "idx_execution_logs_task_id",
        "execution_logs",
        ["task_id"],
    )


def downgrade() -> None:
    """Downgrade schema: drop tables and indexes."""
    # Drop indexes
    op.drop_index("idx_execution_logs_task_id", "execution_logs")
    op.drop_index("idx_tasks_status", "tasks")
    op.drop_index("idx_tasks_created_at", "tasks")

    # Drop tables
    op.drop_table("execution_logs")
    op.drop_table("tasks")
