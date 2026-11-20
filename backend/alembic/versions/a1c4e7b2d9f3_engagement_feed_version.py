"""engagement feed version: a saved artifactory's URL can be edited, with a version check

- engagement_feeds.version: the version an edit names in If-Match (app.auth.versions). Every existing row starts at 1.
- engagement_feeds.updated_at, updated_by: who last edited it, and when. Null until the first edit.

Only adds.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1c4e7b2d9f3'
down_revision: Union[str, None] = 'f8b3d1a7c5e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('engagement_feeds', sa.Column('version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('engagement_feeds', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('engagement_feeds', sa.Column('updated_by', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('engagement_feeds', 'updated_by')
    op.drop_column('engagement_feeds', 'updated_at')
    op.drop_column('engagement_feeds', 'version')
