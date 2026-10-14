"""engine run protocol actions and role

Revision ID: a7d3e9c2f5b1
Revises: f2c8d5a1b7e4
Create Date: 2026-10-14

36-COPILOT-ENHANCED-CONVERSION Part M: a step the runbook prescribes in both arms (Ctrl+C on a stuck terminal) is a
protocol action, recorded apart from interventions; a run can be the pilot, kept and verified but excluded from the
comparison.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a7d3e9c2f5b1'
down_revision: Union[str, None] = 'f2c8d5a1b7e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('engine_runs', sa.Column('protocol_actions', postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column('engine_runs', sa.Column('role', sa.Text(), nullable=False, server_default='comparison'))
    op.add_column('engine_runs', sa.Column('role_reason', sa.Text(), nullable=True))
    op.create_check_constraint('ck_engine_runs_role', 'engine_runs', "role IN ('comparison', 'pilot')")


def downgrade() -> None:
    op.drop_constraint('ck_engine_runs_role', 'engine_runs')
    op.drop_column('engine_runs', 'role_reason')
    op.drop_column('engine_runs', 'role')
    op.drop_column('engine_runs', 'protocol_actions')
