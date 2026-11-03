"""toolchain checks: whether a repository's machine can build and test its baseline

- toolchain_checks: one row per repository, written on the machine it is registered on after discovery (app.toolchain):
  whether that machine has the runtimes and build tools the repository's own frameworks need, with the summary and
  each missing and present one. Lazy: no row means not checked yet, and the page says so.

Only adds a table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c3e9a7b5d1f4'
down_revision: Union[str, None] = 'a1d4e8c2b7f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'toolchain_checks',
        sa.Column('repository_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('host', sa.Text(), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('ready', sa.Boolean(), nullable=False),
        sa.Column('result', postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('toolchain_checks')
