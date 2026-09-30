"""entry_points: origin and entry_class

Revision ID: c2f7a9d3e815
Revises: b8e2f5a1d704
Create Date: 2026-10-01 12:00:00.000000

entry-point-inventory 2.1.0.

origin — application | framework. Framework is a web.config handler or module
registration of a type no project in the repository declares (Application
Insights, session state, Autofac, TransferRequestHandler). Kept, since
IHttpModule registrations matter for the move to middleware, but it migrates
through its package's own path rather than being rewritten.

entry_class — request | lifecycle. Lifecycle is bootstrap and wiring:
Global.asax events, OWIN startup, HTTP modules, hosted and Windows services,
console and desktop mains. Downstream counting, contract snapshots and test
generation read request entry points only, and a lifecycle hook carries no
auth_declared.

Backfill from kind and detail, the same rules the scanner applies; the next
scan rewrites every row anyway.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c2f7a9d3e815'
down_revision: Union[str, None] = 'b8e2f5a1d704'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LIFECYCLE_KINDS = ("global_asax", "owin_startup", "hosted_service", "windows_service", "console_main", "desktop_app")


def upgrade() -> None:
    op.add_column("entry_points", sa.Column("origin", sa.Text(), nullable=False, server_default="application"))
    op.add_column("entry_points", sa.Column("entry_class", sa.Text(), nullable=False, server_default="request"))
    op.execute(
        "UPDATE entry_points SET origin = 'framework' "
        "WHERE kind = 'http_handler' AND detail->>'inRepository' = 'false'"
    )
    op.execute(
        f"UPDATE entry_points SET entry_class = 'lifecycle', auth_declared = NULL "
        f"WHERE kind IN {_LIFECYCLE_KINDS} OR (kind = 'http_handler' AND detail->>'role' = 'module')"
    )
    op.create_check_constraint("ck_entry_points_origin", "entry_points", "origin IN ('application', 'framework')")
    op.create_check_constraint("ck_entry_points_entry_class", "entry_points", "entry_class IN ('request', 'lifecycle')")
    op.create_check_constraint(
        "ck_entry_points_lifecycle_auth", "entry_points", "entry_class = 'request' OR auth_declared IS NULL"
    )


def downgrade() -> None:
    op.drop_constraint("ck_entry_points_lifecycle_auth", "entry_points", type_="check")
    op.drop_constraint("ck_entry_points_entry_class", "entry_points", type_="check")
    op.drop_constraint("ck_entry_points_origin", "entry_points", type_="check")
    op.drop_column("entry_points", "entry_class")
    op.drop_column("entry_points", "origin")
