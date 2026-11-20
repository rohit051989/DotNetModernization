"""package lookup rule: the rule a lookup cache answer was asked under

- package_lookup_cache.lookup_rule: 1 for every existing row, which held listed versions only; dependency-assessment
  1.10.0 writes 2 (every version, unlisted ones marked) and asks a row under an older rule again, whatever its age.
  A lookup made offline, from an experiment's frozen snapshot, uses a row whatever its rule.

Only adds.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b5d2e8f4a1c7'
down_revision: Union[str, None] = 'a1c4e7b2d9f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('package_lookup_cache', sa.Column('lookup_rule', sa.Integer(), nullable=False, server_default='1'))


def downgrade() -> None:
    op.drop_column('package_lookup_cache', 'lookup_rule')
