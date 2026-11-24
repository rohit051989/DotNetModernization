"""resolution confirm design

Revision ID: d4b7e2a9c1f3
Revises: c6e1a9d4f2b8
Create Date: 2026-11-24

36-COPILOT-ENHANCED-CONVERSION "Design questions before converting": a catalog resolution that changes the design or the
architecture (SOAP to REST, a UI rewrite) is flagged, and a conversion's engine asks the developer how to implement its
work items before changing any code. False for every existing row; the seed sets it on the factory resolutions that
change the design, through app/items/baseline.py, never on a row edited since it was seeded.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4b7e2a9c1f3'
down_revision: Union[str, None] = 'c6e1a9d4f2b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('item_resolutions', sa.Column('confirm_design', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('item_resolutions', 'confirm_design')
