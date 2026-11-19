"""conversion engine: GitHub Copilot or Claude Code, an engagement's default and a repository's own choice

- engagements.default_engine: the engine an engagement's conversions use unless a repository chooses its own. Every
  existing engagement takes 'github-copilot', as its conversions always have (36-COPILOT-ENHANCED-CONVERSION Part Q).
- repositories.conversion_engine: the repository owner's choice; null means the engagement's default.

Only adds.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f8b3d1a7c5e2'
down_revision: Union[str, None] = 'e7a2c9d4b1f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENGINES = "('github-copilot', 'claude-code')"


def upgrade() -> None:
    op.add_column('engagements', sa.Column('default_engine', sa.Text(), nullable=False, server_default='github-copilot'))
    op.create_check_constraint('ck_engagements_default_engine', 'engagements', f"default_engine IN {ENGINES}")
    op.add_column('repositories', sa.Column('conversion_engine', sa.Text(), nullable=True))
    op.create_check_constraint('ck_repositories_conversion_engine', 'repositories',
                               f"conversion_engine IS NULL OR conversion_engine IN {ENGINES}")


def downgrade() -> None:
    op.drop_constraint('ck_repositories_conversion_engine', 'repositories', type_='check')
    op.drop_column('repositories', 'conversion_engine')
    op.drop_constraint('ck_engagements_default_engine', 'engagements', type_='check')
    op.drop_column('engagements', 'default_engine')
