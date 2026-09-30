"""item model: forcing pair, candidates, in_review, planned_emits

Revision ID: c3a8f5d20e71
Revises: b7d2e4f81c35
Create Date: 2026-09-29 21:00:00.000000

Corrections to b7d2e4f81c35 agreed after review of 28-ITEM-AND-CONVERSION-MODEL.md:

- engagement_decisions.forcing_rationale: 25-STANDARDS-AND-VIEWPOINTS.md A1
  establishes forcing_perspective and forcing_rationale as a pair; Part F
  had omitted the second half.
- engagement_decisions.candidates_considered: the resolution menu grows
  across engagements, so what was presented at decision time is history
  worth keeping, even though validation judges against the full menu.
- engagement_decisions.status gains 'in_review' (pending / in_review /
  approved / superseded), keeping the pattern records' distinction.
- extractors.planned_emits: a signal an already-implemented extractor will
  gain. Claimed (so not an unclaimed-signal hard error), not ready.

Schema only; additive, and the downgrade reverses it exactly (any in_review
rows are moved back to pending first so the old CHECK can be restored).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3a8f5d20e71'
down_revision: Union[str, None] = 'b7d2e4f81c35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("engagement_decisions", sa.Column("forcing_rationale", sa.Text(), nullable=True))
    op.add_column(
        "engagement_decisions", sa.Column("candidates_considered", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.drop_constraint("ck_engagement_decisions_status", "engagement_decisions", type_="check")
    op.create_check_constraint(
        "ck_engagement_decisions_status",
        "engagement_decisions",
        "status IN ('pending', 'in_review', 'approved', 'superseded')",
    )
    op.add_column(
        "extractors",
        sa.Column(
            "planned_emits", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
    )


def downgrade() -> None:
    op.drop_column("extractors", "planned_emits")
    op.execute("UPDATE engagement_decisions SET status = 'pending' WHERE status = 'in_review'")
    op.drop_constraint("ck_engagement_decisions_status", "engagement_decisions", type_="check")
    op.create_check_constraint(
        "ck_engagement_decisions_status",
        "engagement_decisions",
        "status IN ('pending', 'approved', 'superseded')",
    )
    op.drop_column("engagement_decisions", "candidates_considered")
    op.drop_column("engagement_decisions", "forcing_rationale")
