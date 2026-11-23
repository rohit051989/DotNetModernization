"""decision outcome: an engagement can decide an item is not applicable

- engagement_decisions.outcome: 'resolve' (the decision chooses a resolution, as every decision so far did) or
  'not_applicable' (the item does not apply to this engagement: its findings are kept, marked and counted apart, and it
  is no work: not in the engines' inputs, not remaining for the verifier). Every existing row is 'resolve'.

Only adds.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c6e1a9d4f2b8'
down_revision: Union[str, None] = 'b5d2e8f4a1c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('engagement_decisions', sa.Column('outcome', sa.Text(), nullable=False, server_default='resolve'))
    op.create_check_constraint('ck_engagement_decisions_outcome', 'engagement_decisions',
                               "outcome IN ('resolve', 'not_applicable')")
    # A not-applicable decision chooses no resolution.
    op.create_check_constraint('ck_engagement_decisions_not_applicable_no_resolution', 'engagement_decisions',
                               "outcome <> 'not_applicable' OR resolution_id IS NULL")


def downgrade() -> None:
    op.drop_constraint('ck_engagement_decisions_not_applicable_no_resolution', 'engagement_decisions', type_='check')
    op.drop_constraint('ck_engagement_decisions_outcome', 'engagement_decisions', type_='check')
    op.drop_column('engagement_decisions', 'outcome')
