"""entry_points: the razor_page kind

Revision ID: a6d4e8f21c93
Revises: f3a9c2d7e104
Create Date: 2026-09-30 21:00:00.000000

entry-point-inventory 1.1.0 inventories ASP.NET Core Razor Pages — a .cshtml
with an @page directive and its PageModel handlers — as a twelfth kind.
Only the CHECK constraint changes; the detail JSONB already carries the http
block Razor Pages use.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a6d4e8f21c93'
down_revision: Union[str, None] = 'f3a9c2d7e104'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KINDS_1_0 = (
    "http_controller_action",
    "http_minimal_api",
    "wcf_operation",
    "asmx_web_method",
    "grpc_service_method",
    "signalr_hub_method",
    "message_consumer",
    "hosted_service",
    "scheduled_job",
    "console_main",
    "webforms_page",
)
_KINDS_1_1 = _KINDS_1_0 + ("razor_page",)


def upgrade() -> None:
    op.drop_constraint("ck_entry_points_kind", "entry_points", type_="check")
    op.create_check_constraint("ck_entry_points_kind", "entry_points", f"kind IN {_KINDS_1_1}")


def downgrade() -> None:
    # Razor Page rows cannot satisfy the narrower constraint; they are
    # derived data a rescan with the 1.0.0 scanner would not produce.
    op.execute("DELETE FROM entry_points WHERE kind = 'razor_page'")
    op.drop_constraint("ck_entry_points_kind", "entry_points", type_="check")
    op.create_check_constraint("ck_entry_points_kind", "entry_points", f"kind IN {_KINDS_1_0}")
