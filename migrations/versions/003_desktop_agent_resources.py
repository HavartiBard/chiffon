"""Add resource metrics tracking to agent registry.

Revision ID: 003
Revises: 002
Create Date: 2026-01-20

This migration adds resource metrics tracking:
- resource_metrics: JSON column storing CPU, GPU, memory metrics from agent heartbeats
- GIN index on resource_metrics for efficient JSON queries during capacity queries
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, Sequence[str], None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add resource_metrics column to agent_registry."""
    # Add resource_metrics column with default empty dict
    op.add_column(
        "agent_registry",
        sa.Column(
            "resource_metrics",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )

    # Create GIN index on resource_metrics for efficient JSON queries
    op.create_index(
        "idx_agent_registry_resource_metrics",
        "agent_registry",
        ["resource_metrics"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Downgrade schema: remove resource_metrics column from agent_registry."""
    # Drop index
    op.drop_index(
        "idx_agent_registry_resource_metrics",
        "agent_registry",
    )

    # Drop column
    op.drop_column("agent_registry", "resource_metrics")
