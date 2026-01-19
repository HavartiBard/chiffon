"""Add agent registry and performance tracking tables.

Revision ID: 002
Revises: 001
Create Date: 2026-01-19

This migration creates the agent routing infrastructure:
- agent_registry: tracks agent capabilities, specializations, and status
- agent_performance: records success rates and execution history per work type
- routing_decisions: audit trail for all routing decisions with scoring factors
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, Sequence[str], None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: create agent registry and routing tables."""
    # Create agent_registry table
    op.create_table(
        "agent_registry",
        sa.Column("agent_id", sa.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("agent_type", sa.String(50), nullable=False),
        sa.Column("pool_name", sa.String(100), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("specializations", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="offline"),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Create indexes on agent_registry table
    op.create_index(
        "idx_agent_registry_type_status",
        "agent_registry",
        ["agent_type", "status"],
    )
    op.create_index(
        "idx_agent_registry_pool_name",
        "agent_registry",
        ["pool_name"],
    )

    # Create agent_performance table
    op.create_table(
        "agent_performance",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("agent_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("work_type", sa.String(100), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_execution_at", sa.DateTime(), nullable=True),
        sa.Column("difficulty_assessment", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_registry.agent_id"],
            ondelete="CASCADE",
        ),
    )

    # Create unique constraint on agent_id + work_type
    op.create_unique_constraint(
        "uq_agent_performance_agent_id_work_type",
        "agent_performance",
        ["agent_id", "work_type"],
    )

    # Create indexes on agent_performance table
    op.create_index(
        "idx_agent_performance_agent_id",
        "agent_performance",
        ["agent_id"],
    )

    # Create routing_decisions table
    op.create_table(
        "routing_decisions",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("task_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("work_type", sa.String(100), nullable=False),
        sa.Column("agent_pool", sa.String(100), nullable=False),
        sa.Column("selected_agent_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("success_rate_percent", sa.Integer(), nullable=True),
        sa.Column("specialization_match", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recent_context_match", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retried", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["selected_agent_id"],
            ["agent_registry.agent_id"],
            ondelete="SET NULL",
        ),
    )

    # Create indexes on routing_decisions table
    op.create_index(
        "idx_routing_decisions_task_id",
        "routing_decisions",
        ["task_id"],
    )
    op.create_index(
        "idx_routing_decisions_work_type_created_at",
        "routing_decisions",
        ["work_type", "created_at"],
    )


def downgrade() -> None:
    """Downgrade schema: drop agent registry and routing tables."""
    # Drop indexes
    op.drop_index("idx_routing_decisions_work_type_created_at", "routing_decisions")
    op.drop_index("idx_routing_decisions_task_id", "routing_decisions")
    op.drop_index("idx_agent_performance_agent_id", "agent_performance")
    op.drop_index("idx_agent_registry_pool_name", "agent_registry")
    op.drop_index("idx_agent_registry_type_status", "agent_registry")

    # Drop constraints
    op.drop_constraint("uq_agent_performance_agent_id_work_type", "agent_performance")

    # Drop tables
    op.drop_table("routing_decisions")
    op.drop_table("agent_performance")
    op.drop_table("agent_registry")
