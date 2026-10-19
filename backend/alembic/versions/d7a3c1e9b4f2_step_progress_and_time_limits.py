"""step progress and time limits

Revision ID: d7a3c1e9b4f2
Revises: c9f2a6d1e7b3
Create Date: 2026-10-19

wf_step_executions.progress / progress_at: the last progress a running step reported (phase, items done of the
total, the current item), for the job page and for stall detection. step_time_limits: time and stall limits that
override the defaults, per step, per repository, or both (app.workflow.time_limits). Existing rows are unchanged:
two nullable columns and a new table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd7a3c1e9b4f2'
down_revision: Union[str, None] = 'c9f2a6d1e7b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('wf_step_executions', sa.Column('progress', postgresql.JSONB(), nullable=True))
    op.add_column('wf_step_executions', sa.Column('progress_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        'step_time_limits',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('step_name', sa.Text(), nullable=True),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=True),
        sa.Column('timeout_seconds', sa.Integer(), nullable=True),
        sa.Column('stall_seconds', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('step_name IS NOT NULL OR repository_id IS NOT NULL', name='ck_step_time_limits_scope'),
        sa.CheckConstraint('timeout_seconds IS NULL OR timeout_seconds > 0', name='ck_step_time_limits_timeout'),
        sa.CheckConstraint('stall_seconds IS NULL OR stall_seconds > 0', name='ck_step_time_limits_stall'),
    )
    op.create_index('uq_step_time_limits_scope', 'step_time_limits',
                    [sa.text("coalesce(step_name, '')"), sa.text("coalesce(repository_id::text, '')")], unique=True)


def downgrade() -> None:
    op.drop_index('uq_step_time_limits_scope', table_name='step_time_limits')
    op.drop_table('step_time_limits')
    op.drop_column('wf_step_executions', 'progress_at')
    op.drop_column('wf_step_executions', 'progress')
