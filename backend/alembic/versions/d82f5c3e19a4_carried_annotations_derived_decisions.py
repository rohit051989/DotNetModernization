"""carried annotations; derived decisions

Revision ID: d82f5c3e19a4
Revises: c4a7e1d93b26
Create Date: 2026-10-06 16:00:00.000000

- endpoint_register.annotation_carried_from: annotated hosts step 11 carried to
  a production row when the production grouping moved their calls there
  (31-STEP-011 Part C4). This column was first added by editing c4a7e1d93b26
  after it had been applied; that edit is reverted and the column lives here.
- engagement_decisions.source: 'manual' or 'derived' (28-ITEM Part S). A
  derived decision follows another item's decision — the WCF host and an
  internal NetTcp client follow wcf-service — recorded in
  derived_from_decision_id with the rule that derived it. A derived decision
  overridden by hand becomes manual, keeps the link, and sets
  overrides_derivation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd82f5c3e19a4'
down_revision: Union[str, None] = 'c4a7e1d93b26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('endpoint_register', sa.Column('annotation_carried_from', postgresql.JSONB(astext_type=sa.Text()),
                                                 server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('engagement_decisions', sa.Column('source', sa.Text(), server_default='manual', nullable=False))
    op.add_column('engagement_decisions', sa.Column('derived_from_decision_id', sa.UUID(), nullable=True))
    op.add_column('engagement_decisions', sa.Column('derivation_rule', sa.Text(), nullable=True))
    op.add_column('engagement_decisions', sa.Column('overrides_derivation', sa.Boolean(), server_default='false', nullable=False))
    op.create_foreign_key('fk_engagement_decisions_derived_from', 'engagement_decisions', 'engagement_decisions',
                          ['derived_from_decision_id'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_engagement_decisions_source', 'engagement_decisions', "source IN ('manual', 'derived')")


def downgrade() -> None:
    op.drop_constraint('ck_engagement_decisions_source', 'engagement_decisions', type_='check')
    op.drop_constraint('fk_engagement_decisions_derived_from', 'engagement_decisions', type_='foreignkey')
    op.drop_column('engagement_decisions', 'overrides_derivation')
    op.drop_column('engagement_decisions', 'derivation_rule')
    op.drop_column('engagement_decisions', 'derived_from_decision_id')
    op.drop_column('engagement_decisions', 'source')
    op.drop_column('endpoint_register', 'annotation_carried_from')
