"""Add playbook_cache table for playbook metadata caching

Revision ID: 006_playbook_cache
Revises: 005_playbook_mappings
Create Date: 2026-01-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create playbook_cache table for playbook metadata storage."""
    op.create_table(
        'playbook_cache',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('playbook_path', sa.String(500), nullable=False, unique=True, comment='Full path to playbook file'),
        sa.Column('service_name', sa.String(100), nullable=True, comment='Service name extracted from playbook'),
        sa.Column('description', sa.Text(), nullable=True, comment='Playbook description'),
        sa.Column('required_vars', JSONB, nullable=False, server_default='[]', comment='Required variables as JSON array'),
        sa.Column('tags', JSONB, nullable=False, server_default='[]', comment='Tags as JSON array'),
        sa.Column('file_hash', sa.String(64), nullable=False, comment='SHA256 hash for invalidation'),
        sa.Column('discovered_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()'), comment='When playbook was discovered'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()'), onupdate=sa.text('NOW()'), comment='Last update timestamp'),
        sa.PrimaryKeyConstraint('id')
    )

    # Indexes for query performance
    op.create_index(
        'idx_playbook_cache_service',
        'playbook_cache',
        ['service_name'],
        unique=False
    )
    op.create_index(
        'idx_playbook_cache_path',
        'playbook_cache',
        ['playbook_path'],
        unique=True
    )


def downgrade() -> None:
    """Drop playbook_cache table."""
    op.drop_index('idx_playbook_cache_path', table_name='playbook_cache')
    op.drop_index('idx_playbook_cache_service', table_name='playbook_cache')
    op.drop_table('playbook_cache')
