"""Add playbook_mappings table for semantic mapping cache

Revision ID: 005_playbook_mappings
Revises: 004_audit_columns
Create Date: 2026-01-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = '005_playbook_mappings'
down_revision = '004_audit_columns'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create playbook_mappings table for semantic mapping cache."""
    op.create_table(
        'playbook_mappings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('intent', sa.String(500), nullable=False, comment='Task intent text'),
        sa.Column('intent_hash', sa.String(64), nullable=False, comment='SHA256 of normalized intent'),
        sa.Column('playbook_path', sa.String(500), nullable=False, comment='Path to playbook file'),
        sa.Column('confidence', sa.Float(), nullable=False, comment='Match confidence (0.0-1.0)'),
        sa.Column('match_method', sa.String(50), nullable=False, comment='exact|cached|semantic'),
        sa.Column('embedding_vector', JSONB, nullable=True, comment='Embedding as JSON array'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('last_used_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('use_count', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('intent_hash', name='uq_playbook_mappings_intent_hash')
    )

    # Indexes for query performance
    op.create_index(
        'idx_playbook_mappings_confidence',
        'playbook_mappings',
        ['confidence'],
        unique=False
    )


def downgrade() -> None:
    """Drop playbook_mappings table."""
    op.drop_index('idx_playbook_mappings_confidence', table_name='playbook_mappings')
    op.drop_table('playbook_mappings')
