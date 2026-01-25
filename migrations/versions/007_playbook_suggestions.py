"""Add playbook_suggestions table for improvement tracking

Revision ID: 007_playbook_suggestions
Revises: 006_playbook_cache
Create Date: 2026-01-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create playbook_suggestions table for storing improvement suggestions."""
    op.create_table(
        'playbook_suggestions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('playbook_path', sa.String(500), nullable=False, comment='Path to playbook that needs improvement'),
        sa.Column('task_id', UUID(as_uuid=True), nullable=True, comment='FK to tasks if from execution'),
        sa.Column('category', sa.String(50), nullable=False, comment='Suggestion category: idempotency, error_handling, performance, best_practices, standards'),
        sa.Column('rule_id', sa.String(100), nullable=False, comment='ansible-lint rule ID'),
        sa.Column('message', sa.Text(), nullable=False, comment='Lint message from ansible-lint'),
        sa.Column('reasoning', sa.Text(), nullable=True, comment='Human-readable explanation of why this matters'),
        sa.Column('line_number', sa.Integer(), nullable=True, comment='Line number in playbook where issue found'),
        sa.Column('severity', sa.String(20), nullable=False, comment='Severity: error, warning, info'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending', comment='Status: pending, applied, dismissed'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()'), comment='When suggestion was created'),
        sa.Column('resolved_at', sa.DateTime(), nullable=True, comment='When suggestion was applied or dismissed'),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.task_id'], name='fk_suggestions_task_id', ondelete='SET NULL')
    )

    # Indexes for query performance
    op.create_index(
        'idx_suggestions_playbook',
        'playbook_suggestions',
        ['playbook_path'],
        unique=False
    )
    op.create_index(
        'idx_suggestions_category',
        'playbook_suggestions',
        ['category'],
        unique=False
    )
    op.create_index(
        'idx_suggestions_status',
        'playbook_suggestions',
        ['status'],
        unique=False
    )


def downgrade() -> None:
    """Drop playbook_suggestions table."""
    op.drop_index('idx_suggestions_status', table_name='playbook_suggestions')
    op.drop_index('idx_suggestions_category', table_name='playbook_suggestions')
    op.drop_index('idx_suggestions_playbook', table_name='playbook_suggestions')
    op.drop_table('playbook_suggestions')
