"""conversion failure policy by dependency

Revision ID: e81b4c2d9a07
Revises: d05f33540904
Create Date: 2026-10-12 14:10:00.000000

34-CONVERSION-ARCHITECTURE.md Part E, "Failure policy: by dependency, not by
phase": every unit records what it depends on (conversion_units.depends_on),
a failure blocks exactly its dependents (unit status `blocked`), and a plan
whose units were all tried or stood down, some not green, ends `partial`
rather than `stopped`. No catalog row is written here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e81b4c2d9a07'
down_revision: Union[str, None] = 'd05f33540904'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_UNIT = ("planned", "applied", "verified", "committed", "not_applicable", "failed", "stale",
            "awaiting_review", "awaiting_human", "excluded")
NEW_UNIT = ("planned", "applied", "verified", "committed", "not_applicable", "failed", "blocked", "stale",
            "awaiting_review", "awaiting_human", "excluded")
OLD_PLAN = ("planned", "running", "completed", "stopped")
NEW_PLAN = ("planned", "running", "completed", "partial", "stopped")


def upgrade() -> None:
    op.add_column('conversion_units', sa.Column('depends_on', postgresql.JSONB(astext_type=sa.Text()),
                                                server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.drop_constraint('ck_conversion_units_status', 'conversion_units', type_='check')
    op.create_check_constraint('ck_conversion_units_status', 'conversion_units', f"status IN {NEW_UNIT}")
    op.drop_constraint('ck_conversion_plans_status', 'conversion_plans', type_='check')
    op.create_check_constraint('ck_conversion_plans_status', 'conversion_plans', f"status IN {NEW_PLAN}")


def downgrade() -> None:
    op.drop_constraint('ck_conversion_plans_status', 'conversion_plans', type_='check')
    op.create_check_constraint('ck_conversion_plans_status', 'conversion_plans', f"status IN {OLD_PLAN}")
    op.drop_constraint('ck_conversion_units_status', 'conversion_units', type_='check')
    op.create_check_constraint('ck_conversion_units_status', 'conversion_units', f"status IN {OLD_UNIT}")
    op.drop_column('conversion_units', 'depends_on')
