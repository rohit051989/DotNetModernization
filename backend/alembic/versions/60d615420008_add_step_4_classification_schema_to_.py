"""add step 4 classification schema to patterns

Revision ID: 60d615420008
Revises: 73e0ffd22d29
Create Date: 2026-08-20 16:26:04.025697

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '60d615420008'
down_revision: Union[str, None] = '73e0ffd22d29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMPTY_SIGNAL_RULE_SET = '{"schema": "signal-rules/1.0"}'
_DEFAULT_THRESHOLDS = '{"minimumScore": 70, "highConfidenceScore": 90}'


def upgrade() -> None:
    # ### 24-STEP-004-CLASSIFICATION.md Part B1 — new columns on patterns ###
    op.add_column('patterns', sa.Column('classification_role', sa.Text(), server_default='PRIMARY', nullable=False))
    op.add_column('patterns', sa.Column('classification_family', sa.Text(), nullable=True))
    op.add_column('patterns', sa.Column('classification_value', sa.Text(), nullable=True))
    op.add_column('patterns', sa.Column('scope', sa.Text(), server_default='PROJECT', nullable=False))
    op.add_column('patterns', sa.Column('priority', sa.Integer(), server_default='50', nullable=False))
    op.add_column('patterns', sa.Column('compatible_with', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('patterns', sa.Column('conflicts_with', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('patterns', sa.Column('anchor_signals', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('patterns', sa.Column('eligibility', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('patterns', sa.Column('analysis_requirements', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('patterns', sa.Column('thresholds', postgresql.JSONB(astext_type=sa.Text()), server_default=_DEFAULT_THRESHOLDS, nullable=False))
    op.add_column('patterns', sa.Column('rules_status', sa.Text(), server_default='draft', nullable=False))
    op.add_column('patterns', sa.Column('required_signals_pending', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('patterns', sa.Column('detection_rules_legacy', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.create_check_constraint(
        'ck_patterns_classification_role', 'patterns', "classification_role IN ('PRIMARY', 'SECONDARY', 'PROJECT_ROLE')"
    )
    op.create_check_constraint('ck_patterns_scope', 'patterns', "scope IN ('PROJECT', 'REPOSITORY')")
    op.create_check_constraint(
        'ck_patterns_rules_status', 'patterns', "rules_status IN ('active', 'awaiting_signals', 'draft')"
    )
    op.create_index('ix_patterns_rules_status', 'patterns', ['rules_status'], unique=False)

    # `detection_rules_legacy` preserves what every pre-existing pattern's
    # `detection_rules` held before this migration — the existing tag-input
    # editor is repointed at this column so it keeps working unchanged.
    op.execute("UPDATE patterns SET detection_rules_legacy = detection_rules")

    # `detection_rules` now holds the Part C signal-rules/1.0 structure.
    # Every pre-existing pattern gets the inert empty stub here — re-authoring
    # real rules onto it is J2, explicitly out of scope for this migration.
    # `rules_status` defaults every pattern to 'draft', so nothing is
    # evaluated (rules_status: active only) until J2 promotes it.
    op.execute(f"UPDATE patterns SET detection_rules = '{_EMPTY_SIGNAL_RULE_SET}'::jsonb")

    # ### catalog_revisions — 24-STEP-004-CLASSIFICATION.md Part H ###
    op.create_table(
        'catalog_revisions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Text(), nullable=False),
        sa.Column('operation', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("entity_type IN ('pattern', 'target_state_option')", name='ck_catalog_revisions_entity_type'),
        sa.CheckConstraint("operation IN ('insert', 'update', 'soft_delete')", name='ck_catalog_revisions_operation'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_catalog_revisions_entity', 'catalog_revisions', ['entity_type', 'entity_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_catalog_revisions_entity', table_name='catalog_revisions')
    op.drop_table('catalog_revisions')

    op.drop_index('ix_patterns_rules_status', table_name='patterns')
    op.drop_constraint('ck_patterns_rules_status', 'patterns', type_='check')
    op.drop_constraint('ck_patterns_scope', 'patterns', type_='check')
    op.drop_constraint('ck_patterns_classification_role', 'patterns', type_='check')

    # Restore detection_rules from detection_rules_legacy before dropping it,
    # so downgrading gives the old tag-input editor its data back.
    op.execute("UPDATE patterns SET detection_rules = detection_rules_legacy WHERE detection_rules_legacy IS NOT NULL")

    op.drop_column('patterns', 'detection_rules_legacy')
    op.drop_column('patterns', 'required_signals_pending')
    op.drop_column('patterns', 'rules_status')
    op.drop_column('patterns', 'thresholds')
    op.drop_column('patterns', 'analysis_requirements')
    op.drop_column('patterns', 'eligibility')
    op.drop_column('patterns', 'anchor_signals')
    op.drop_column('patterns', 'conflicts_with')
    op.drop_column('patterns', 'compatible_with')
    op.drop_column('patterns', 'priority')
    op.drop_column('patterns', 'scope')
    op.drop_column('patterns', 'classification_value')
    op.drop_column('patterns', 'classification_family')
    op.drop_column('patterns', 'classification_role')
