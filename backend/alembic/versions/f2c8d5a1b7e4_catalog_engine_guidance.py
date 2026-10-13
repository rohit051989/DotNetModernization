"""catalog engine guidance

Revision ID: f2c8d5a1b7e4
Revises: e8b1c4d6a273
Create Date: 2026-10-14

36-COPILOT-ENHANCED-CONVERSION Part K: catalog items and resolutions get engine-facing guidance, kept apart from
their author-facing descriptions. Null where none is written yet.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f2c8d5a1b7e4'
down_revision: Union[str, None] = 'e8b1c4d6a273'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('catalog_items', sa.Column('engine_guidance', sa.Text(), nullable=True))
    op.add_column('item_resolutions', sa.Column('engine_guidance', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('item_resolutions', 'engine_guidance')
    op.drop_column('catalog_items', 'engine_guidance')
