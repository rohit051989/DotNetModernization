"""step 11 estate dependency map: register, annotations, package estate, graph, reconciliations

Revision ID: 67405849f1c2
Revises: f1c7a3e9d2b5
Create Date: 2026-10-03 21:59:42.425642

31-STEP-011-ESTATE-DEPENDENCY-MAP.md Part G. Engagement-scoped client data.
Step 11 replaces every table here per engagement on each run, except
endpoint_annotations: human notes keyed by the register's host, which a run
never writes, so they survive rescans (Part C4). estate_sources records which
step execution of each repository a run read (Part B1).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '67405849f1c2'
down_revision: Union[str, None] = 'f1c7a3e9d2b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('dependency_cycles',
    sa.Column('engagement_id', sa.Text(), nullable=False),
    sa.Column('cycle_id', sa.Text(), nullable=False),
    sa.Column('member_project_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('cross_repository', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('engagement_id', 'cycle_id')
    )
    op.create_table('endpoint_annotations',
    sa.Column('engagement_id', sa.Text(), nullable=False),
    sa.Column('host', sa.Text(), nullable=False),
    sa.Column('owning_team', sa.Text(), nullable=True),
    sa.Column('contact', sa.Text(), nullable=True),
    sa.Column('conversation_status', sa.Text(), server_default='not_started', nullable=False),
    sa.Column('target_date', sa.Date(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('updated_by', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("conversation_status IN ('not_started', 'in_progress', 'agreed', 'resolved', 'not_required')", name='ck_endpoint_annotations_status'),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('engagement_id', 'host')
    )
    op.create_table('endpoint_register',
    sa.Column('engagement_id', sa.Text(), nullable=False),
    sa.Column('host', sa.Text(), nullable=False),
    sa.Column('classification', sa.Text(), nullable=False),
    sa.Column('loopback', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('no_longer_called', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('calling_repository_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('calling_repositories', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('calling_project_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('calling_projects', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('mechanisms', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('bindings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('ports', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('worst_verdict', sa.Text(), nullable=True),
    sa.Column('verdict_by_environment', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('requires_backend_change', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('backend_change_reasons', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('invocation_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('step_execution_id', sa.UUID(), nullable=True),
    sa.CheckConstraint("classification IN ('internal', 'external')", name='ck_endpoint_register_classification'),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('engagement_id', 'host')
    )
    op.create_table('endpoint_register_services',
    sa.Column('engagement_id', sa.Text(), nullable=False),
    sa.Column('host', sa.Text(), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('contract', sa.Text(), server_default='', nullable=False),
    sa.Column('ports', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('mechanisms', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('bindings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('calling_repositories', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('calling_projects', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('worst_verdict', sa.Text(), nullable=True),
    sa.Column('requires_backend_change', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('internal', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('internal_targets', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('engagement_id', 'host', 'path', 'contract')
    )
    op.create_table('package_estate',
    sa.Column('engagement_id', sa.Text(), nullable=False),
    sa.Column('package_id', sa.Text(), nullable=False),
    sa.Column('repository_count', sa.Integer(), nullable=False),
    sa.Column('repositories', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('project_count', sa.Integer(), nullable=False),
    sa.Column('projects', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('versions_in_use', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('estate_drift', sa.Boolean(), nullable=False),
    sa.Column('cross_repository_drift', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('recommended_version', sa.Text(), nullable=True),
    sa.Column('outcomes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('breaking_members', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('flags', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('engagement_id', 'package_id')
    )
    op.create_table('estate_sources',
    sa.Column('engagement_id', sa.Text(), nullable=False),
    sa.Column('repository_id', sa.UUID(), nullable=False),
    sa.Column('step_name', sa.Text(), nullable=False),
    sa.Column('step_execution_id', sa.UUID(), nullable=True),
    sa.Column('estate_step_execution_id', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('engagement_id', 'repository_id', 'step_name')
    )
    op.create_table('dependency_edges',
    sa.Column('engagement_id', sa.Text(), nullable=False),
    sa.Column('from_project_id', sa.UUID(), nullable=False),
    sa.Column('to_project_id', sa.UUID(), nullable=False),
    sa.Column('edge_kind', sa.Text(), nullable=False),
    sa.Column('cross_repository', sa.Boolean(), nullable=False),
    sa.Column('via_package', sa.Text(), nullable=True),
    sa.Column('client_feed', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("edge_kind IN ('project_reference', 'internal_package')", name='ck_dependency_edges_kind'),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['from_project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['to_project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('engagement_id', 'from_project_id', 'to_project_id', 'edge_kind')
    )
    op.create_table('origin_reconciliations',
    sa.Column('engagement_id', sa.Text(), nullable=False),
    sa.Column('entry_point_id', sa.Text(), nullable=False),
    sa.Column('original_origin', sa.Text(), nullable=False),
    sa.Column('reconciled_origin', sa.Text(), nullable=False),
    sa.Column('declaring_repository_id', sa.UUID(), nullable=False),
    sa.Column('declaring_project_id', sa.UUID(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['declaring_project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['declaring_repository_id'], ['repositories.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('engagement_id', 'entry_point_id')
    )
    op.create_table('shared_libraries',
    sa.Column('engagement_id', sa.Text(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('consumer_repository_count', sa.Integer(), nullable=False),
    sa.Column('consumer_project_count', sa.Integer(), nullable=False),
    sa.Column('consumers', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('engagement_id', 'project_id')
    )


def downgrade() -> None:
    op.drop_table('shared_libraries')
    op.drop_table('origin_reconciliations')
    op.drop_table('dependency_edges')
    op.drop_table('estate_sources')
    op.drop_table('package_estate')
    op.drop_table('endpoint_register_services')
    op.drop_table('endpoint_register')
    op.drop_table('endpoint_annotations')
    op.drop_table('dependency_cycles')
