"""conversion scope: which of a repository's projects its conversions cover

- conversion_scopes: one row per repository whose scope someone saved (app.scope). Lazy: no row means every project
  is in scope, so every existing repository converts exactly as it did. Only the excluded projects are stored, by
  path relative to the repository, with every project known at the save (to flag a project discovered later), who
  saved it, from which machine, when, the reason and a version for the edit check.

Only adds a table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1d4e8c2b7f3'
down_revision: Union[str, None] = 'f7b3d1e9a4c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'conversion_scopes',
        sa.Column('repository_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('repositories.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('excluded_projects', postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('known_projects', postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('treatment', sa.Text(), nullable=False, server_default='leave_untouched'),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('saved_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('saved_by_name', sa.Text(), nullable=False),
        sa.Column('saved_on', sa.Text(), nullable=True),
        sa.Column('saved_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.CheckConstraint("treatment IN ('leave_untouched')", name='ck_conversion_scopes_treatment'),
    )


def downgrade() -> None:
    op.drop_table('conversion_scopes')
