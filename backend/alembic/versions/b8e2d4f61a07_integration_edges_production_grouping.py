"""step 5 invoked operations; step 11 integration edges, production-host grouping, served_by_repository

Revision ID: b8e2d4f61a07
Revises: 67405849f1c2
Create Date: 2026-10-03 23:40:00.000000

- outbound_invocations.operations: what each call site invokes (step 5,
  outbound-invocation-inventory 1.2.0).
- engagements.production_environment: the environment whose host names a
  service in the endpoint register (31-STEP-011 Part C1). Null: group by the
  host as found.
- endpoint_annotations.served_by_repository_id: a human's statement that a
  host is served by one of the estate's repositories, so HTTP calls to it are
  matched against that repository's routes. Human data, never written by a run.
- endpoint_register.grouped_by / other_hosts: how each row was grouped, and
  the other environments' hosts beneath it.
- integration_edges / integration_entry_points: operation-level matches of
  step 5's invoked operations to step 4's entry points, replaced per run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b8e2d4f61a07'
down_revision: Union[str, None] = '67405849f1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('outbound_invocations', sa.Column('operations', postgresql.JSONB(astext_type=sa.Text()),
                                                    server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('engagements', sa.Column('production_environment', sa.Text(), nullable=True))
    op.add_column('endpoint_annotations', sa.Column('served_by_repository_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_endpoint_annotations_served_by_repository', 'endpoint_annotations', 'repositories',
                          ['served_by_repository_id'], ['id'], ondelete='SET NULL')
    op.add_column('endpoint_register', sa.Column('grouped_by', sa.Text(), server_default='host', nullable=False))
    op.add_column('endpoint_register', sa.Column('other_hosts', postgresql.JSONB(astext_type=sa.Text()),
                                                 server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.create_check_constraint('ck_endpoint_register_grouped_by', 'endpoint_register',
                               "grouped_by IN ('production_environment', 'host')")

    op.create_table('integration_edges',
    sa.Column('engagement_id', sa.Text(), nullable=False),
    sa.Column('edge_id', sa.Text(), nullable=False),
    sa.Column('mechanism', sa.Text(), nullable=False),
    sa.Column('caller_repository_id', sa.UUID(), nullable=False),
    sa.Column('caller_project_id', sa.UUID(), nullable=False),
    sa.Column('invocation_id', sa.Text(), nullable=False),
    sa.Column('call_site_file', sa.Text(), nullable=False),
    sa.Column('call_site_line', sa.Integer(), nullable=False),
    sa.Column('operation', sa.Text(), nullable=False),
    sa.Column('callee_repository_id', sa.UUID(), nullable=False),
    sa.Column('callee_project_id', sa.UUID(), nullable=False),
    sa.Column('entry_point_id', sa.Text(), nullable=False),
    sa.Column('match_method', sa.Text(), nullable=False),
    sa.Column('confidence', sa.Numeric(3, 2), nullable=False),
    sa.Column('same_repository', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('engagement_id', 'edge_id')
    )
    op.create_index('ix_integration_edges_entry_point', 'integration_edges', ['engagement_id', 'entry_point_id'])
    op.create_table('integration_entry_points',
    sa.Column('engagement_id', sa.Text(), nullable=False),
    sa.Column('entry_point_id', sa.Text(), nullable=False),
    sa.Column('repository_id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('operation', sa.Text(), nullable=False),
    sa.Column('matchable', sa.Boolean(), nullable=False),
    sa.Column('internal_caller', sa.Text(), nullable=False),
    sa.Column('caller_count', sa.Integer(), nullable=False),
    sa.Column('cross_repository_caller_count', sa.Integer(), nullable=False),
    sa.CheckConstraint("internal_caller IN ('internal_caller_found', 'no_internal_caller_found')",
                       name='ck_integration_entry_points_internal_caller'),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('engagement_id', 'entry_point_id')
    )


def downgrade() -> None:
    op.drop_table('integration_entry_points')
    op.drop_index('ix_integration_edges_entry_point', table_name='integration_edges')
    op.drop_table('integration_edges')
    op.drop_constraint('ck_endpoint_register_grouped_by', 'endpoint_register', type_='check')
    op.drop_column('endpoint_register', 'other_hosts')
    op.drop_column('endpoint_register', 'grouped_by')
    op.drop_constraint('fk_endpoint_annotations_served_by_repository', 'endpoint_annotations', type_='foreignkey')
    op.drop_column('endpoint_annotations', 'served_by_repository_id')
    op.drop_column('engagements', 'production_environment')
    op.drop_column('outbound_invocations', 'operations')
