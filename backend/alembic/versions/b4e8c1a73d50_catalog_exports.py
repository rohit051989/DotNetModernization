"""catalog exports

Revision ID: b4e8c1a73d50
Revises: a3d9e6f20b17
Create Date: 2026-10-06 22:00:00.000000

catalog_exports: one row per run of the item catalog export into the
repository's catalog/items/, with a hash per item, so the UI and dashboard
can show what changed in the database since the files in git were written
(28-ITEM Part W). Nothing exports automatically.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b4e8c1a73d50'
down_revision: Union[str, None] = 'a3d9e6f20b17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'catalog_exports',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('exported_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('catalog_hash', sa.Text(), nullable=False),
        sa.Column('item_count', sa.Integer(), nullable=False),
        sa.Column('items', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('out_dir', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('catalog_exports')
