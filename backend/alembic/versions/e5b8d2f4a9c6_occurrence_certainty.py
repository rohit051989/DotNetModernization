"""item_occurrences.certainty: confirmed | possible

Revision ID: e5b8d2f4a9c6
Revises: d7a2c4e8f1b3
Create Date: 2026-10-03 14:00:00.000000

An occurrence is 'possible' when every piece of evidence behind it is
ambiguous — today, a package-upgrade-breaking file whose only call sites an
unchanged overload could equally take. The work list shows possible rows
apart and work totals leave them out by default. Existing rows are
confirmed until the next rescan recomputes them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5b8d2f4a9c6'
down_revision: Union[str, None] = 'd7a2c4e8f1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("item_occurrences", sa.Column("certainty", sa.Text(), nullable=False, server_default="confirmed"))
    op.create_check_constraint("ck_item_occurrences_certainty", "item_occurrences", "certainty IN ('confirmed', 'possible')")


def downgrade() -> None:
    op.drop_constraint("ck_item_occurrences_certainty", "item_occurrences", type_="check")
    op.drop_column("item_occurrences", "certainty")
