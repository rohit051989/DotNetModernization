"""repository hosting OS: where the application is hosted now and where it is going

- repositories.current_hosting_os and repositories.target_hosting_os: 'windows' or 'linux', set by an admin. They
  decide whether the repository page's Compatibility tab shows its Linux list (only windows to linux).
  Existing repositories get windows and linux, so they show it as before.

Only adds columns, each with a default, and a check on each.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4b8f2a6c1e9'
down_revision: Union[str, None] = 'c3e9a7b5d1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('repositories', sa.Column('current_hosting_os', sa.Text(), nullable=False, server_default='windows'))
    op.add_column('repositories', sa.Column('target_hosting_os', sa.Text(), nullable=False, server_default='linux'))
    op.create_check_constraint('ck_repositories_current_hosting_os', 'repositories',
                               "current_hosting_os IN ('windows', 'linux')")
    op.create_check_constraint('ck_repositories_target_hosting_os', 'repositories',
                               "target_hosting_os IN ('windows', 'linux')")


def downgrade() -> None:
    op.drop_constraint('ck_repositories_target_hosting_os', 'repositories', type_='check')
    op.drop_constraint('ck_repositories_current_hosting_os', 'repositories', type_='check')
    op.drop_column('repositories', 'target_hosting_os')
    op.drop_column('repositories', 'current_hosting_os')
