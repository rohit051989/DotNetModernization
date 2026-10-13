"""package outcome framework_provided

Revision ID: e8b1c4d6a273
Revises: d3a5f7c19b42
Create Date: 2026-10-13

dependency-assessment 1.4.0 (30-DEPENDENCY-ASSESSMENT): a package the target framework's shared framework already
provides (Microsoft.AspNetCore.Server.Kestrel 2.x in a Web project) is a removal, not an upgrade. Adds
framework_provided to ck_package_assessments_outcome.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e8b1c4d6a273'
down_revision: Union[str, None] = 'd3a5f7c19b42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BEFORE = "('current', 'upgrade_safe', 'upgrade_breaking', 'no_compatible_version', 'unknown')"
AFTER = "('current', 'upgrade_safe', 'upgrade_breaking', 'no_compatible_version', 'framework_provided', 'unknown')"


def upgrade() -> None:
    op.drop_constraint('ck_package_assessments_outcome', 'package_assessments')
    op.create_check_constraint('ck_package_assessments_outcome', 'package_assessments', f"outcome IN {AFTER}")


def downgrade() -> None:
    op.execute("DELETE FROM package_assessments WHERE outcome = 'framework_provided'")
    op.drop_constraint('ck_package_assessments_outcome', 'package_assessments')
    op.create_check_constraint('ck_package_assessments_outcome', 'package_assessments', f"outcome IN {BEFORE}")
