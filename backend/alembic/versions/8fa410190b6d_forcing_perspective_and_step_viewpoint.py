"""forcing perspective and step viewpoint

Revision ID: 8fa410190b6d
Revises: 9ff0c70b7d79
Create Date: 2026-08-27 20:22:00.140695

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8fa410190b6d'
down_revision: Union[str, None] = '9ff0c70b7d79'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A1 — 25-STANDARDS-AND-VIEWPOINTS.md Part A1.
    op.alter_column("decision_records", "forcing_factor", new_column_name="forcing_rationale")
    op.add_column("decision_records", sa.Column("forcing_perspective", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_decision_records_forcing_perspective",
        "decision_records",
        "forcing_perspective IS NULL OR forcing_perspective IN "
        "('SECURITY', 'EVOLUTION', 'REGULATION', 'PERFORMANCE_SCALABILITY', "
        "'AVAILABILITY_RESILIENCE', 'LOCATION', 'DEVELOPMENT_RESOURCE')",
    )

    # A2 — 25-STANDARDS-AND-VIEWPOINTS.md Part A2.
    op.add_column("wf_step_registrations", sa.Column("viewpoint", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_wf_step_registrations_viewpoint",
        "wf_step_registrations",
        "viewpoint IS NULL OR viewpoint IN "
        "('CONTEXT', 'FUNCTIONAL', 'INFORMATION', 'CONCURRENCY', 'DEVELOPMENT', "
        "'DEPLOYMENT', 'OPERATIONAL', 'NONE')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_wf_step_registrations_viewpoint", "wf_step_registrations", type_="check")
    op.drop_column("wf_step_registrations", "viewpoint")

    op.drop_constraint("ck_decision_records_forcing_perspective", "decision_records", type_="check")
    op.drop_column("decision_records", "forcing_perspective")
    op.alter_column("decision_records", "forcing_rationale", new_column_name="forcing_factor")
