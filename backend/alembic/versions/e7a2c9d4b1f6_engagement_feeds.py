"""engagement feeds: the NuGet feeds an engagement's scans ask, beside the ones a repository's NuGet.config declares

- engagement_feeds: one row per feed an engagement lists in its Artifactory tab (name, URL, and the URL normalised
  for the duplicate check). Shared by every developer on the database. Never a credential: a feed's login comes from
  NuGet.config or the environment of the machine that scans (docs/39-ARTIFACTORY-FEEDS.md). Soft-deleted, so a removed
  URL can be added again: one live row per (engagement, normalised URL).

Only adds.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e7a2c9d4b1f6'
down_revision: Union[str, None] = 'd4b8f2a6c1e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'engagement_feeds',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('engagement_id', sa.Text(), sa.ForeignKey('engagements.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('url_normalised', sa.Text(), nullable=False),
        sa.Column('created_by', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
        sa.Column('deleted_by', sa.Text()),
    )
    op.create_index('uq_engagement_feeds_live_url', 'engagement_feeds', ['engagement_id', 'url_normalised'],
                    unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_engagement_feeds_live_name', 'engagement_feeds', ['engagement_id', sa.text('lower(name)')],
                    unique=True, postgresql_where=sa.text('deleted_at IS NULL'))


def downgrade() -> None:
    op.drop_index('uq_engagement_feeds_live_name', table_name='engagement_feeds')
    op.drop_index('uq_engagement_feeds_live_url', table_name='engagement_feeds')
    op.drop_table('engagement_feeds')
