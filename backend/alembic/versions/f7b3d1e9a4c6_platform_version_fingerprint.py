"""platform version fingerprint: what the database depends on, beside the commit

- platform_version.fingerprint: the migration head, each step registration's version and the seed data's hash, as
  recorded by an admin's bootstrap (app.platform_version). In our own development repository the version check
  compares these, not the commit, so a commit that changes none of them needs no update; installations keep comparing
  commits.

Only adds a nullable column. A version recorded before it has no fingerprint, and is compared by commit until the
admin's next bootstrap records one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f7b3d1e9a4c6'
down_revision: Union[str, None] = 'e6a2c9d3f8b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('platform_version', sa.Column('fingerprint', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('platform_version', 'fingerprint')
