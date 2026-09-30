"""add item catalog model

Revision ID: b7d2e4f81c35
Revises: e5c1d7a93f20
Create Date: 2026-09-29 19:09:19.845684

28-ITEM-AND-CONVERSION-MODEL.md Parts C-G: the catalog half of the item and
conversion model, created ALONGSIDE the pattern tables. Nothing here alters
patterns, target_state_options, decision_records, engagement_patterns or the
step 4 classification tables; Part Q runs both models side by side until the
new one is verified against the old.

Schema only. Populating extractors and signal_registry_entries is the seed's
job (registry files); moving patterns into catalog_items is a separate,
reversible data migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b7d2e4f81c35'
down_revision: Union[str, None] = 'e5c1d7a93f20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('catalog_items',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('category', sa.Text(), nullable=False),
    sa.Column('detection', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('excluded_roles', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('state', sa.Text(), server_default='not_ready', nullable=False),
    sa.Column('state_reason', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('owner_team', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default='active', nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("category IN ('hosting', 'logging', 'configuration', 'security', 'data-access', 'integration', 'packaging', 'dependencies', 'framework')", name='ck_catalog_items_category'),
    sa.CheckConstraint("scope IN ('application', 'occurrence')", name='ck_catalog_items_scope'),
    sa.CheckConstraint("state IN ('ready', 'not_ready')", name='ck_catalog_items_state'),
    sa.CheckConstraint("status IN ('active', 'deprecated')", name='ck_catalog_items_status'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_catalog_items_state', 'catalog_items', ['state'], unique=False)
    op.create_table('extractors',
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('emits', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('owner_team', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('implemented', 'planned')", name='ck_extractors_status'),
    sa.PrimaryKeyConstraint('name')
    )
    op.create_table('engagement_item_scope',
    sa.Column('engagement_id', sa.Text(), nullable=False),
    sa.Column('item_id', sa.Text(), nullable=False),
    sa.Column('scope_status', sa.Text(), server_default='active', nullable=False),
    sa.Column('deferred_reason', sa.Text(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("scope_status IN ('active', 'deferred')", name='ck_engagement_item_scope_scope_status'),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ),
    sa.ForeignKeyConstraint(['item_id'], ['catalog_items.id'], ),
    sa.PrimaryKeyConstraint('engagement_id', 'item_id')
    )
    op.create_index('ix_engagement_item_scope_engagement_id', 'engagement_item_scope', ['engagement_id'], unique=False)
    op.create_table('item_resolutions',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('item_id', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('target_description', sa.Text(), nullable=True),
    sa.Column('consumer_impact', sa.Text(), nullable=False),
    sa.Column('effort', sa.Text(), nullable=False),
    sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('linux_compatible', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('container_ready', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default='active', nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("consumer_impact IN ('none', 'low', 'medium', 'high')", name='ck_item_resolutions_consumer_impact'),
    sa.CheckConstraint("effort IN ('low', 'medium', 'high')", name='ck_item_resolutions_effort'),
    sa.CheckConstraint("status IN ('active', 'deprecated')", name='ck_item_resolutions_status'),
    sa.ForeignKeyConstraint(['item_id'], ['catalog_items.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('item_id', 'name', name='uq_item_resolutions_item_id_name')
    )
    op.create_index('ix_item_resolutions_item_id', 'item_resolutions', ['item_id'], unique=False)
    op.create_index('uq_item_resolutions_one_default', 'item_resolutions', ['item_id'], unique=True, postgresql_where=sa.text('is_default AND deleted_at IS NULL'))
    op.create_table('signal_registry_entries',
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('category', sa.Text(), nullable=False),
    sa.Column('type', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('expected_extractor', sa.Text(), nullable=False),
    sa.Column('evidence_kind', sa.Text(), nullable=False),
    sa.Column('value_semantics', sa.Text(), nullable=True),
    sa.Column('signal_introduced_in_version', sa.Text(), nullable=False),
    sa.Column('state', sa.Text(), server_default='not_ready', nullable=False),
    sa.Column('state_reason', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("category IN ('PROJECT_METADATA', 'FRAMEWORK_REFERENCE', 'PACKAGE_DEPENDENCY', 'SOURCE_CONSTRUCT', 'FILE_INDICATOR', 'CONFIGURATION_INDICATOR', 'ENTRY_POINT', 'ENDPOINT_INDICATOR', 'EXECUTION_INDICATOR', 'HOSTING_INDICATOR', 'UI_INDICATOR', 'DATA_ACCESS_INDICATOR', 'MESSAGING_INDICATOR', 'SCHEDULING_INDICATOR', 'DEPLOYMENT_INDICATOR', 'TESTING_INDICATOR')", name='ck_signal_registry_entries_category'),
    sa.CheckConstraint("evidence_kind IN ('FILE', 'FOLDER', 'NONE')", name='ck_signal_registry_entries_evidence_kind'),
    sa.CheckConstraint("state IN ('ready', 'not_ready')", name='ck_signal_registry_entries_state'),
    sa.CheckConstraint("type IN ('ATTRIBUTE', 'BASE_CLASS', 'FILE_PRESENCE', 'INVOCATION', 'CONFIG_ELEMENT', 'PACKAGE', 'ASSEMBLY', 'NAMESPACE', 'ROUTE', 'ENTRY_POINT')", name='ck_signal_registry_entries_type'),
    sa.ForeignKeyConstraint(['expected_extractor'], ['extractors.name'], ),
    sa.PrimaryKeyConstraint('name')
    )
    op.create_table('engagement_decisions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('engagement_id', sa.Text(), nullable=False),
    sa.Column('item_id', sa.Text(), nullable=False),
    sa.Column('resolution_id', sa.Text(), nullable=True),
    sa.Column('rationale', sa.Text(), nullable=True),
    sa.Column('forcing_perspective', sa.Text(), nullable=True),
    sa.Column('evaluation_notes', sa.Text(), nullable=True),
    sa.Column('approver_name', sa.Text(), nullable=True),
    sa.Column('approver_role', sa.Text(), nullable=True),
    sa.Column('decision_date', sa.Date(), nullable=True),
    sa.Column('status', sa.Text(), server_default='pending', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("forcing_perspective IS NULL OR forcing_perspective IN ('SECURITY', 'EVOLUTION', 'REGULATION', 'PERFORMANCE_SCALABILITY', 'AVAILABILITY_RESILIENCE', 'LOCATION', 'DEVELOPMENT_RESOURCE')", name='ck_engagement_decisions_forcing_perspective'),
    sa.CheckConstraint("status IN ('pending', 'approved', 'superseded')", name='ck_engagement_decisions_status'),
    sa.ForeignKeyConstraint(['engagement_id'], ['engagements.id'], ),
    sa.ForeignKeyConstraint(['item_id'], ['catalog_items.id'], ),
    sa.ForeignKeyConstraint(['resolution_id'], ['item_resolutions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_engagement_decisions_engagement_id', 'engagement_decisions', ['engagement_id'], unique=False)
    op.create_index('uq_engagement_decisions_live', 'engagement_decisions', ['engagement_id', 'item_id'], unique=True, postgresql_where=sa.text("status <> 'superseded'"))
    op.create_table('item_occurrences',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('repository_id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('item_id', sa.Text(), nullable=False),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('file_path', sa.Text(), nullable=True),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('signal_registry_version', sa.Text(), nullable=False),
    sa.Column('detection_state', sa.Text(), nullable=False),
    sa.Column('step_execution_id', sa.UUID(), nullable=True),
    sa.Column('detected_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(file_path IS NOT NULL) = (scope = 'occurrence' AND detection_state = 'found')", name='ck_item_occurrences_file_path'),
    sa.CheckConstraint("detection_state IN ('found', 'checked_absent', 'not_checked')", name='ck_item_occurrences_detection_state'),
    sa.CheckConstraint("scope IN ('application', 'occurrence')", name='ck_item_occurrences_scope'),
    sa.ForeignKeyConstraint(['item_id'], ['catalog_items.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_item_occurrences_item_id', 'item_occurrences', ['item_id'], unique=False)
    op.create_index('ix_item_occurrences_repository_id', 'item_occurrences', ['repository_id'], unique=False)
    op.create_index('uq_item_occurrences_located', 'item_occurrences', ['project_id', 'item_id', 'file_path'], unique=True, postgresql_where=sa.text('file_path IS NOT NULL'))
    op.create_index('uq_item_occurrences_project', 'item_occurrences', ['project_id', 'item_id'], unique=True, postgresql_where=sa.text('file_path IS NULL'))


def downgrade() -> None:
    op.drop_index('uq_item_occurrences_project', table_name='item_occurrences', postgresql_where=sa.text('file_path IS NULL'))
    op.drop_index('uq_item_occurrences_located', table_name='item_occurrences', postgresql_where=sa.text('file_path IS NOT NULL'))
    op.drop_index('ix_item_occurrences_repository_id', table_name='item_occurrences')
    op.drop_index('ix_item_occurrences_item_id', table_name='item_occurrences')
    op.drop_table('item_occurrences')
    op.drop_index('uq_engagement_decisions_live', table_name='engagement_decisions', postgresql_where=sa.text("status <> 'superseded'"))
    op.drop_index('ix_engagement_decisions_engagement_id', table_name='engagement_decisions')
    op.drop_table('engagement_decisions')
    op.drop_table('signal_registry_entries')
    op.drop_index('uq_item_resolutions_one_default', table_name='item_resolutions', postgresql_where=sa.text('is_default AND deleted_at IS NULL'))
    op.drop_index('ix_item_resolutions_item_id', table_name='item_resolutions')
    op.drop_table('item_resolutions')
    op.drop_index('ix_engagement_item_scope_engagement_id', table_name='engagement_item_scope')
    op.drop_table('engagement_item_scope')
    op.drop_table('extractors')
    op.drop_index('ix_catalog_items_state', table_name='catalog_items')
    op.drop_table('catalog_items')
