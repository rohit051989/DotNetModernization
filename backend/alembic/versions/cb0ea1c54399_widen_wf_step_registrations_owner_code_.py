"""widen wf_step_registrations owner_code to allow combined codes

Revision ID: cb0ea1c54399
Revises: 902afd93be37
Create Date: 2026-08-14 15:55:06.592271

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cb0ea1c54399'
down_revision: Union[str, None] = '902afd93be37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_wf_step_registrations_owner_code", "wf_step_registrations", type_="check"
    )
    op.create_check_constraint(
        "ck_wf_step_registrations_owner_code",
        "wf_step_registrations",
        "owner_code IN ('P', 'C', 'S', 'H', 'P + S', 'P + H')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_wf_step_registrations_owner_code", "wf_step_registrations", type_="check"
    )
    op.create_check_constraint(
        "ck_wf_step_registrations_owner_code",
        "wf_step_registrations",
        "owner_code IN ('P', 'C', 'S', 'H')",
    )
