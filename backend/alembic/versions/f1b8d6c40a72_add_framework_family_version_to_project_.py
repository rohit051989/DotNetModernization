"""add framework_family/version to project_classifications

Revision ID: f1b8d6c40a72
Revises: d5a7c3e91b04
Create Date: 2026-09-02 14:30:00.000000

24-STEP-004-CLASSIFICATION.md Part F — echoed onto the classification so
the artifact is self-contained and downstream consumers (step 10's risk
scoring, an accelerator deciding which breaking changes apply) do not have
to join back to step 2's `projects` table. Both nullable: step 2 leaves
them null for a project with no parseable target framework.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1b8d6c40a72'
down_revision: Union[str, None] = 'd5a7c3e91b04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("project_classifications", sa.Column("framework_family", sa.Text(), nullable=True))
    op.add_column("project_classifications", sa.Column("framework_version", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("project_classifications", "framework_version")
    op.drop_column("project_classifications", "framework_family")
