"""platform heartbeat and deletion audit

Revision ID: b5e1d8c3a904
Revises: a7d3e9c2f5b1
Create Date: 2026-10-16

platform_heartbeat: the one running platform using this schema, refreshed while it runs, so a second platform
started on the same schema refuses to start (docs/VDI-SETUP.md section N). deletion_audit: one row per hard delete
of a repository or an engagement — what, by whom, when — kept apart from the data it describes, so it survives it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b5e1d8c3a904'
down_revision: Union[str, None] = 'a7d3e9c2f5b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'platform_heartbeat',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('instance_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('host', sa.Text(), nullable=False),
        sa.Column('os_user', sa.Text(), nullable=False),
        sa.Column('pid', sa.Integer(), nullable=False),
        sa.Column('platform_root', sa.Text(), nullable=False),
        sa.Column('api_port', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('beat_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('id = 1', name='ck_platform_heartbeat_single_row'),
    )
    op.create_table(
        'deletion_audit',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_by', sa.Text(), nullable=False),
        sa.Column('via', sa.Text(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('engagement_id', sa.Text(), nullable=False),
        sa.Column('repository_slug', sa.Text(), nullable=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('summary', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("kind IN ('repository', 'engagement')", name='ck_deletion_audit_kind'),
    )
    op.create_index('ix_deletion_audit_deleted_at', 'deletion_audit', ['deleted_at'])


def downgrade() -> None:
    op.drop_index('ix_deletion_audit_deleted_at', table_name='deletion_audit')
    op.drop_table('deletion_audit')
    op.drop_table('platform_heartbeat')
