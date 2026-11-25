"""resolution phase

Revision ID: e7a3c5f9b2d4
Revises: d4b7e2a9c1f3
Create Date: 2026-11-25

36-COPILOT-ENHANCED-CONVERSION "Phases": each catalog resolution has a phase, 1 to 6 (project format, libraries,
replace framework-only dependencies, retarget and host applications, platform and deployment, decisions a person still
has to make), and a conversion's plan orders its work items by phase, then by the project dependency graph. Null for
every existing row; the seed sets the factory phases through app/items/baseline.py, never on a row edited since it was
seeded. Additive: nothing existing changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e7a3c5f9b2d4'
down_revision: Union[str, None] = 'd4b7e2a9c1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('item_resolutions', sa.Column('phase', sa.SmallInteger(), nullable=True))
    op.create_check_constraint('ck_item_resolutions_phase', 'item_resolutions', 'phase IS NULL OR phase BETWEEN 1 AND 6')


def downgrade() -> None:
    op.drop_constraint('ck_item_resolutions_phase', 'item_resolutions', type_='check')
    op.drop_column('item_resolutions', 'phase')
