"""step 5 1.3.0: SetParameters globs, construction sites, entry point backend reach

Revision ID: c4a7e1d93b26
Revises: b8e2d4f61a07
Create Date: 2026-10-06 10:00:00.000000

- engagements.deploy_parameter_globs: where Web Deploy SetParameters files are
  (29-STEPS Part C9, 1.3.0). Null means the defaults, **/SetParam*.xml and
  **/SetParameters*.xml.
- outbound_invocations.construction_sites: where a client is created, kept
  apart from call_sites, which are now where it is invoked.
- entry_point_backend: per step 4 entry point, the outbound call sites it
  reaches — written by step 5, replaced per repository like its other tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c4a7e1d93b26'
down_revision: Union[str, None] = 'b8e2d4f61a07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('engagements', sa.Column('deploy_parameter_globs', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('outbound_invocations', sa.Column('construction_sites', postgresql.JSONB(astext_type=sa.Text()),
                                                    server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.create_table('entry_point_backend',
    sa.Column('entry_point_id', sa.Text(), nullable=False),
    sa.Column('repository_id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('calls', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('unresolved', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('step_execution_id', sa.UUID(), nullable=True),
    sa.CheckConstraint("status IN ('yes', 'no', 'unresolved')", name='ck_entry_point_backend_status'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('repository_id', 'entry_point_id')
    )


def downgrade() -> None:
    op.drop_table('entry_point_backend')
    op.drop_column('outbound_invocations', 'construction_sites')
    op.drop_column('engagements', 'deploy_parameter_globs')
