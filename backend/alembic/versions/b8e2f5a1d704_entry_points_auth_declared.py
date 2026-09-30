"""entry_points: auth_declared replaces unauthorised; seven new kinds

Revision ID: b8e2f5a1d704
Revises: a6d4e8f21c93
Create Date: 2026-10-01 10:00:00.000000

entry-point-inventory 2.0.0.

`unauthorised` (bool) becomes `auth_declared` (declared | none_declared |
not_assessed, null where it does not apply). Gateway, proxy and header-based
authentication are invisible to static analysis, so "none declared" is a
review prompt, not a finding that an entry point is open — the old name said
the second.

Backfill: false -> declared; true -> none_declared; null -> not_assessed for
the kinds called from outside, null otherwise. Rows are derived data and the
next scan rewrites them anyway.

The kind constraint gains windows_service, http_handler, global_asax,
owin_startup, blazor_component, azure_function and desktop_app.

entry_point_scans gains `capabilities`: the capability manifest version and
kinds the scan ran against, so a kind it did not look for reads as a gap, not
as "none found".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b8e2f5a1d704'
down_revision: Union[str, None] = 'a6d4e8f21c93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KINDS_1_1 = (
    "http_controller_action", "http_minimal_api", "wcf_operation", "asmx_web_method", "grpc_service_method",
    "signalr_hub_method", "message_consumer", "hosted_service", "scheduled_job", "console_main", "webforms_page",
    "razor_page",
)
_NEW_KINDS = ("windows_service", "http_handler", "global_asax", "owin_startup", "blazor_component", "azure_function", "desktop_app")
_KINDS_2_0 = _KINDS_1_1 + _NEW_KINDS
_CALLED_FROM_OUTSIDE = (
    "http_controller_action", "http_minimal_api", "razor_page", "wcf_operation", "asmx_web_method",
    "grpc_service_method", "signalr_hub_method", "webforms_page",
)
_AUTH_DECLARED = ("declared", "none_declared", "not_assessed")


def upgrade() -> None:
    op.add_column("entry_points", sa.Column("auth_declared", sa.Text(), nullable=True))
    op.execute(
        f"""
        UPDATE entry_points SET auth_declared = CASE
            WHEN unauthorised IS FALSE THEN 'declared'
            WHEN unauthorised IS TRUE THEN 'none_declared'
            WHEN kind IN {_CALLED_FROM_OUTSIDE} THEN 'not_assessed'
        END
        """
    )
    op.create_check_constraint(
        "ck_entry_points_auth_declared", "entry_points", f"auth_declared IS NULL OR auth_declared IN {_AUTH_DECLARED}"
    )
    op.drop_column("entry_points", "unauthorised")

    op.drop_constraint("ck_entry_points_kind", "entry_points", type_="check")
    op.create_check_constraint("ck_entry_points_kind", "entry_points", f"kind IN {_KINDS_2_0}")

    op.add_column("entry_point_scans", sa.Column("capabilities", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("entry_point_scans", "capabilities")
    op.execute(f"DELETE FROM entry_points WHERE kind IN {_NEW_KINDS}")
    op.drop_constraint("ck_entry_points_kind", "entry_points", type_="check")
    op.create_check_constraint("ck_entry_points_kind", "entry_points", f"kind IN {_KINDS_1_1}")

    op.add_column("entry_points", sa.Column("unauthorised", sa.Boolean(), nullable=True))
    op.execute(
        """
        UPDATE entry_points SET unauthorised = CASE auth_declared
            WHEN 'declared' THEN FALSE
            WHEN 'none_declared' THEN TRUE
        END
        """
    )
    op.drop_constraint("ck_entry_points_auth_declared", "entry_points", type_="check")
    op.drop_column("entry_points", "auth_declared")
