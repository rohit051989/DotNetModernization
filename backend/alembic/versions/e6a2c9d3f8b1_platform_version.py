"""platform version: the version of the platform the database is at, recorded by an admin's bootstrap

- platform_version: one row per update: our commit (PLATFORM_SOURCE.json on an installation, HEAD in our own
  repository), its commit date, the migration head, who recorded it and from which machine. The newest row is the
  database's version; a developer's bootstrap and every backend compare their own with it (app.platform_version).

Only adds. Until an admin's bootstrap records one, the database has no version: a developer is told to ask the admin to
update first.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e6a2c9d3f8b1'
down_revision: Union[str, None] = 'd4f1b8c2e7a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'platform_version',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('commit', sa.Text(), nullable=False),
        sa.Column('committed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('migration', sa.Text(), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('recorded_by', sa.Text(), nullable=False),
        sa.Column('hostname', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('platform_version')
