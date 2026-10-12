"""outbound SOAP runtime verdict

Revision ID: f3a9c6e1b245
Revises: e81b4c2d9a07
Create Date: 2026-10-12 15:20:00.000000

outbound-invocation-inventory 1.4.0 (29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md
C10): a SOAP client's runtime verdict — does the target .NET's WCF client
support its binding, security mode and credential type — beside the
platform (Linux) verdict. The invocation's worst; each environment binding
carries its own in environment_bindings. Null for every other mechanism.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f3a9c6e1b245'
down_revision: Union[str, None] = 'e81b4c2d9a07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RUNTIME_VERDICT = ("unsupported", "unknown", "supported_with_caveat", "supported")


def upgrade() -> None:
    op.add_column('outbound_invocations', sa.Column('runtime_verdict', sa.Text(), nullable=True))
    op.add_column('outbound_invocations', sa.Column('runtime_reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_check_constraint('ck_outbound_invocations_runtime_verdict', 'outbound_invocations',
                               f"runtime_verdict IS NULL OR runtime_verdict IN {RUNTIME_VERDICT}")


def downgrade() -> None:
    op.drop_constraint('ck_outbound_invocations_runtime_verdict', 'outbound_invocations', type_='check')
    op.drop_column('outbound_invocations', 'runtime_reasons')
    op.drop_column('outbound_invocations', 'runtime_verdict')
