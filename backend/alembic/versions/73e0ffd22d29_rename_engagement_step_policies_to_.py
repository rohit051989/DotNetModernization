"""rename engagement_step_policies to step_policies, add global layer

Revision ID: 73e0ffd22d29
Revises: 237dc23cf0e7
Create Date: 2026-08-19 17:05:00.000000

23-WORKFLOW-ADMINISTRATION.md Part A: a global policy layer sits between
default and engagement. Nullable engagement_id means global; the two former
implicit invariants ("one row per (engagement, step)" and "reason only
required when disabling") both change shape here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '73e0ffd22d29'
down_revision: Union[str, None] = '237dc23cf0e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table('engagement_step_policies', 'step_policies')

    # Cosmetic but deliberate: a plain table rename leaves the old
    # auto-generated constraint/index names in place otherwise.
    op.execute("ALTER TABLE step_policies RENAME CONSTRAINT engagement_step_policies_pkey TO step_policies_pkey")
    op.execute(
        "ALTER TABLE step_policies RENAME CONSTRAINT "
        "engagement_step_policies_engagement_id_fkey TO step_policies_engagement_id_fkey"
    )
    op.execute(
        "ALTER TABLE step_policies RENAME CONSTRAINT "
        "engagement_step_policies_step_name_fkey TO step_policies_step_name_fkey"
    )
    op.execute("ALTER INDEX ix_engagement_step_policies_engagement_id RENAME TO ix_step_policies_engagement_id")

    # engagement_id becomes nullable — NULL means global (Part A).
    op.alter_column('step_policies', 'engagement_id', existing_type=sa.Text(), nullable=True)

    # A plain UNIQUE(engagement_id, step_name) treats every NULL
    # engagement_id as distinct, which would allow multiple global rows for
    # the same step. Replace with two partial unique indexes.
    op.drop_constraint('uq_engagement_step_policies_engagement_step', 'step_policies', type_='unique')
    op.create_index(
        'uq_step_policies_global_step',
        'step_policies',
        ['step_name'],
        unique=True,
        postgresql_where=sa.text('engagement_id IS NULL'),
    )
    op.create_index(
        'uq_step_policies_engagement_step',
        'step_policies',
        ['engagement_id', 'step_name'],
        unique=True,
        postgresql_where=sa.text('engagement_id IS NOT NULL'),
    )

    # reason is now required in either direction (Part A: "Why is this step
    # running for Client A when it is globally off" needs an answer as much
    # as the reverse). No existing rows to backfill — table is empty as of
    # this migration.
    op.drop_constraint('ck_engagement_step_policies_reason_required', 'step_policies', type_='check')
    op.alter_column('step_policies', 'reason', existing_type=sa.Text(), nullable=False)

    # Split POLICY_DISABLED into layer-specific skip reasons. Existing
    # historical rows all predate the global layer, so they were necessarily
    # engagement-scoped disables. Drop the old CHECK before the UPDATE —
    # the new value isn't valid under the old constraint yet.
    op.drop_constraint('ck_wf_step_executions_skip_reason', 'wf_step_executions', type_='check')
    op.execute("UPDATE wf_step_executions SET skip_reason = 'POLICY_DISABLED_ENGAGEMENT' WHERE skip_reason = 'POLICY_DISABLED'")
    op.create_check_constraint(
        'ck_wf_step_executions_skip_reason',
        'wf_step_executions',
        "skip_reason IS NULL OR skip_reason IN "
        "('POLICY_DISABLED_GLOBAL', 'POLICY_DISABLED_ENGAGEMENT', 'CONDITION_FALSE', 'TIER_NOT_APPLICABLE', 'UPSTREAM_SKIPPED', 'CASCADED_POLICY')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_wf_step_executions_skip_reason', 'wf_step_executions', type_='check')
    op.execute("UPDATE wf_step_executions SET skip_reason = 'POLICY_DISABLED' WHERE skip_reason IN ('POLICY_DISABLED_GLOBAL', 'POLICY_DISABLED_ENGAGEMENT')")
    op.create_check_constraint(
        'ck_wf_step_executions_skip_reason',
        'wf_step_executions',
        "skip_reason IS NULL OR skip_reason IN "
        "('POLICY_DISABLED', 'CONDITION_FALSE', 'TIER_NOT_APPLICABLE', 'UPSTREAM_SKIPPED', 'CASCADED_POLICY')",
    )

    op.alter_column('step_policies', 'reason', existing_type=sa.Text(), nullable=True)
    op.create_check_constraint(
        'ck_engagement_step_policies_reason_required', 'step_policies', 'enabled OR reason IS NOT NULL'
    )

    op.drop_index('uq_step_policies_engagement_step', table_name='step_policies')
    op.drop_index('uq_step_policies_global_step', table_name='step_policies')
    # Any global (engagement_id IS NULL) rows make this fail — expected: a
    # downgrade past the global layer cannot represent them.
    op.create_unique_constraint(
        'uq_engagement_step_policies_engagement_step', 'step_policies', ['engagement_id', 'step_name']
    )
    op.alter_column('step_policies', 'engagement_id', existing_type=sa.Text(), nullable=False)

    op.execute("ALTER INDEX ix_step_policies_engagement_id RENAME TO ix_engagement_step_policies_engagement_id")
    op.execute(
        "ALTER TABLE step_policies RENAME CONSTRAINT "
        "step_policies_step_name_fkey TO engagement_step_policies_step_name_fkey"
    )
    op.execute(
        "ALTER TABLE step_policies RENAME CONSTRAINT "
        "step_policies_engagement_id_fkey TO engagement_step_policies_engagement_id_fkey"
    )
    op.execute("ALTER TABLE step_policies RENAME CONSTRAINT step_policies_pkey TO engagement_step_policies_pkey")

    op.rename_table('step_policies', 'engagement_step_policies')
