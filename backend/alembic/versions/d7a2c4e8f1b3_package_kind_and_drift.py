"""step 6 artifact 1.1.0: package_kind, breaking_evidence, content_breaking_possible, version_drift

Revision ID: d7a2c4e8f1b3
Revises: c3f9a1d5e724
Create Date: 2026-10-03 09:00:00.000000

Additive. package_kind (runtime | build | tools | analyzer | content) is
derived from the package's own contents; only a runtime package can be
upgrade_breaking, so classification_method gains 'package_kind' for the
build, tools, analyzer and content packages decided by kind alone.
breaking_evidence says what an upgrade_breaking outcome rests on, including
call sites that syntax cannot bind to one overload. Existing rows keep NULL
and false until the next rescan replaces them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd7a2c4e8f1b3'
down_revision: Union[str, None] = 'c3f9a1d5e724'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("package_assessments", sa.Column("package_kind", sa.Text()))
    op.add_column("package_assessments", sa.Column("breaking_evidence", sa.Text()))
    op.add_column("package_assessments", sa.Column("content_breaking_possible", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("package_assessments", sa.Column("version_drift", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.drop_constraint("ck_package_assessments_method", "package_assessments", type_="check")
    op.create_check_constraint(
        "ck_package_assessments_method", "package_assessments",
        "classification_method IS NULL OR classification_method IN ('api_diff', 'semver_heuristic', 'package_kind')",
    )
    op.create_check_constraint(
        "ck_package_assessments_kind", "package_assessments",
        "package_kind IS NULL OR package_kind IN ('runtime', 'build', 'tools', 'analyzer', 'content')",
    )
    op.create_check_constraint(
        "ck_package_assessments_breaking_evidence", "package_assessments",
        "breaking_evidence IS NULL OR breaking_evidence IN ('confirmed_call_sites', 'ambiguous_call_sites_only', 'semver_presumed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_package_assessments_breaking_evidence", "package_assessments", type_="check")
    op.drop_constraint("ck_package_assessments_kind", "package_assessments", type_="check")
    op.execute("UPDATE package_assessments SET classification_method = NULL WHERE classification_method = 'package_kind'")
    op.drop_constraint("ck_package_assessments_method", "package_assessments", type_="check")
    op.create_check_constraint(
        "ck_package_assessments_method", "package_assessments",
        "classification_method IS NULL OR classification_method IN ('api_diff', 'semver_heuristic')",
    )
    op.drop_column("package_assessments", "version_drift")
    op.drop_column("package_assessments", "content_breaking_possible")
    op.drop_column("package_assessments", "breaking_evidence")
    op.drop_column("package_assessments", "package_kind")
