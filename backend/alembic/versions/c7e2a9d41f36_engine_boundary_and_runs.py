"""engine boundary and engine runs

Revision ID: c7e2a9d41f36
Revises: b4d8f1a3c925
Create Date: 2026-10-12

36-COPILOT-ENHANCED-CONVERSION Part I:
- engagements.engine_allowlist: the engines and LLM providers an engagement's
  code may be sent to, [{provider, organisation}]. Empty for every existing and
  new engagement: nothing is allowed until a person sets it.
- engine_runs: one person-executed engine run, recorded at its start with the
  signed-in identity, organisation, model, engine version and a hash per input
  file. No column holds a credential.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c7e2a9d41f36'
down_revision: Union[str, None] = 'b4d8f1a3c925'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('engagements', sa.Column('engine_allowlist', postgresql.JSONB(astext_type=sa.Text()),
                                           server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.create_table('engine_runs',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('engagement_id', sa.Text(), nullable=False),
    sa.Column('repository_id', sa.UUID(), nullable=True),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('provider', sa.Text(), nullable=False),
    sa.Column('organisation', sa.Text(), nullable=False),
    sa.Column('signed_in_identity', sa.Text(), nullable=False),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('engine_version', sa.Text(), nullable=False),
    sa.Column('host', sa.Text(), nullable=True),
    sa.Column('worktree_path', sa.Text(), nullable=True),
    sa.Column('branch', sa.Text(), nullable=True),
    sa.Column('base_commit', sa.Text(), nullable=True),
    sa.Column('inputs', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('outcome', sa.Text(), nullable=True),
    sa.Column('head_commit', sa.Text(), nullable=True),
    sa.Column('elapsed_minutes', sa.Integer(), nullable=True),
    sa.Column('premium_requests', sa.Integer(), nullable=True),
    sa.Column('interventions', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('transcript', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.CheckConstraint("outcome IS NULL OR outcome IN ('completed', 'stopped', 'abandoned')", name='ck_engine_runs_outcome'),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id']),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id']),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('engagement_id', 'label', name='uq_engine_runs_label')
    )


def downgrade() -> None:
    op.drop_table('engine_runs')
    op.drop_column('engagements', 'engine_allowlist')
