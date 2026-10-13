"""package deprecation scope

Revision ID: d3a5f7c19b42
Revises: c7e2a9d41f36
Create Date: 2026-10-13

dependency-assessment 1.3.0 (30-DEPENDENCY-ASSESSMENT Part C3): a deprecated version of a maintained package
is told apart from a retired package. package_assessments.deprecation_scope is "package" or "version"; null
where the package is not deprecated, and for rows written before 1.3.0 until the repository is rescanned.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd3a5f7c19b42'
down_revision: Union[str, None] = 'c7e2a9d41f36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('package_assessments', sa.Column('deprecation_scope', sa.Text(), nullable=True))
    op.create_check_constraint('ck_package_assessments_deprecation_scope', 'package_assessments',
                               "deprecation_scope IS NULL OR deprecation_scope IN ('package', 'version')")


def downgrade() -> None:
    op.drop_constraint('ck_package_assessments_deprecation_scope', 'package_assessments')
    op.drop_column('package_assessments', 'deprecation_scope')
