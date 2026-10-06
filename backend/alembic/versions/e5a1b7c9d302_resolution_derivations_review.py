"""resolution derivations; overrides flagged for review

Revision ID: e5a1b7c9d302
Revises: d82f5c3e19a4
Create Date: 2026-10-06 18:00:00.000000

- resolution_derivations: what choosing a leading item's resolution means for
  each dependent item (derive a resolution, not derived, subsume, not
  subsumed), as master catalog data authored beside the resolution
  (28-ITEM Part U). Replaces the rules held in code in app/items/coupling.py.
- engagement_decisions.derivation_rule becomes derived_against_resolution_id:
  the leader's resolution a decision was derived from or overridden against.
  Existing values named code rules; they are replaced by the leader decision's
  resolution.
- engagement_decisions.needs_review / review_note: an override made against a
  leading decision that has since changed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5a1b7c9d302'
down_revision: Union[str, None] = 'd82f5c3e19a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'resolution_derivations',
        sa.Column('resolution_id', sa.Text(), nullable=False),
        sa.Column('dependent_item_id', sa.Text(), nullable=False),
        sa.Column('item_id', sa.Text(), nullable=False),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('dependent_resolution_id', sa.Text(), nullable=True),
        sa.Column('applies_to', sa.Text(), server_default='all', nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("action IN ('derive', 'not_derived', 'subsume', 'not_subsumed')", name='ck_resolution_derivations_action'),
        sa.CheckConstraint("applies_to IN ('all', 'internal_clients')", name='ck_resolution_derivations_applies_to'),
        sa.CheckConstraint("(action = 'derive') = (dependent_resolution_id IS NOT NULL)",
                           name='ck_resolution_derivations_derive_names_resolution'),
        sa.CheckConstraint('dependent_item_id <> item_id', name='ck_resolution_derivations_not_self'),
        sa.ForeignKeyConstraint(['resolution_id'], ['item_resolutions.id']),
        sa.ForeignKeyConstraint(['dependent_item_id'], ['catalog_items.id']),
        sa.ForeignKeyConstraint(['item_id'], ['catalog_items.id']),
        sa.ForeignKeyConstraint(['dependent_resolution_id'], ['item_resolutions.id']),
        sa.PrimaryKeyConstraint('resolution_id', 'dependent_item_id'),
    )
    op.create_index('ix_resolution_derivations_item_id', 'resolution_derivations', ['item_id'])
    op.create_index('ix_resolution_derivations_dependent_item_id', 'resolution_derivations', ['dependent_item_id'])

    op.alter_column('engagement_decisions', 'derivation_rule', new_column_name='derived_against_resolution_id')
    op.execute("""
        UPDATE engagement_decisions d
        SET derived_against_resolution_id = leader.resolution_id
        FROM engagement_decisions leader
        WHERE d.derived_from_decision_id = leader.id
    """)
    op.execute("UPDATE engagement_decisions SET derived_against_resolution_id = NULL WHERE derived_from_decision_id IS NULL")
    op.create_foreign_key('fk_engagement_decisions_derived_against', 'engagement_decisions', 'item_resolutions',
                          ['derived_against_resolution_id'], ['id'], ondelete='SET NULL')
    op.add_column('engagement_decisions', sa.Column('needs_review', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('engagement_decisions', sa.Column('review_note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('engagement_decisions', 'review_note')
    op.drop_column('engagement_decisions', 'needs_review')
    op.drop_constraint('fk_engagement_decisions_derived_against', 'engagement_decisions', type_='foreignkey')
    op.alter_column('engagement_decisions', 'derived_against_resolution_id', new_column_name='derivation_rule')
    op.drop_index('ix_resolution_derivations_dependent_item_id', table_name='resolution_derivations')
    op.drop_index('ix_resolution_derivations_item_id', table_name='resolution_derivations')
    op.drop_table('resolution_derivations')
