"""catalog seed baselines

Revision ID: a3d9e6f20b17
Revises: e5a1b7c9d302
Create Date: 2026-10-06 20:00:00.000000

seeded_hash on catalog_items, item_resolutions and resolution_derivations: a
hash of the content the seed last wrote (app/items/baseline.py). The
database is authoritative for the catalog; a reseed never overwrites a row
edited since it was seeded.

No backfill: which existing rows were edited in the UI cannot be proved from
the data, so every existing row starts with no baseline. The next seed adopts
a row whose content equals its factory default, and reports any other as a
conflict without changing it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a3d9e6f20b17'
down_revision: Union[str, None] = 'e5a1b7c9d302'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ('catalog_items', 'item_resolutions', 'resolution_derivations')


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column('seeded_hash', sa.Text(), nullable=True))


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, 'seeded_hash')
