"""engagement guidance and field-level seed baselines

Revision ID: f8b4d6a1c3e5
Revises: e7a3c5f9b2d4
Create Date: 2026-11-26

Three additions, nothing existing changed (rule 15):
- `seeded_fields` on catalog_items, item_resolutions and resolution_derivations: {field: digest of the value the seed
  last wrote}, so a reseed works field by field (rule 10): a field an admin never changed is still seeded on a row
  whose other fields were edited. Null on every existing row; app/items/baseline.py records it on its next write.
- `engagements.conventions`: one engagement's conventions (logging, naming, error format), carried in the top-level
  instructions of each of its conversions.
- `engagement_resolution_notes`: one engagement's note on one catalog resolution, carried after the master guidance in
  its conversions' work items; engagement data, never the master catalog (rule 6). Deleted with its engagement.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f8b4d6a1c3e5'
down_revision: Union[str, None] = 'e7a3c5f9b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ('catalog_items', 'item_resolutions', 'resolution_derivations'):
        op.add_column(table, sa.Column('seeded_fields', postgresql.JSONB(), nullable=True))
    op.add_column('engagements', sa.Column('conventions', sa.Text(), nullable=True))
    op.create_table(
        'engagement_resolution_notes',
        sa.Column('engagement_id', sa.Text(), sa.ForeignKey('engagements.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('resolution_id', sa.Text(), sa.ForeignKey('item_resolutions.id'), primary_key=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('updated_by', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('engagement_resolution_notes')
    op.drop_column('engagements', 'conventions')
    for table in ('catalog_items', 'item_resolutions', 'resolution_derivations'):
        op.drop_column(table, 'seeded_fields')
