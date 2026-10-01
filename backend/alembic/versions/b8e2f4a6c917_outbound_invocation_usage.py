"""step 5 outbound-invocation inventory 1.1.0: outbound_invocations.usage

Revision ID: b8e2f4a6c917
Revises: a5d1e7c9b203
Create Date: 2026-10-01 16:00:00.000000

usage is 'used' or 'unused'. An unused client — a ClientBase subclass that
nothing constructs and nothing configures — makes no outbound call. Its row
is kept, but step 10's endpoint register must read usage = 'used' only, so
nobody asks a backend team about an endpoint nothing calls. Indexed with
endpoint_host because that is the pair the register filters and groups on.

Per-environment verdicts live inside environment_bindings (JSONB) and need
no column. Derived data: existing rows default to 'used' and the next scan
rewrites them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b8e2f4a6c917'
down_revision: Union[str, None] = 'a5d1e7c9b203'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outbound_invocations", sa.Column("usage", sa.Text(), nullable=False, server_default="used"))
    op.create_check_constraint("ck_outbound_invocations_usage", "outbound_invocations", "usage IN ('used', 'unused')")
    op.create_index("ix_outbound_invocations_usage_endpoint_host", "outbound_invocations", ["usage", "endpoint_host"])


def downgrade() -> None:
    op.drop_index("ix_outbound_invocations_usage_endpoint_host", table_name="outbound_invocations")
    op.drop_constraint("ck_outbound_invocations_usage", "outbound_invocations", type_="check")
    op.drop_column("outbound_invocations", "usage")
