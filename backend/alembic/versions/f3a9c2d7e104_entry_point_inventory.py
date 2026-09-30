"""step 4 entry-point inventory: entry_points and entry_point_scans

Revision ID: f3a9c2d7e104
Revises: e8b3c61f0a94
Create Date: 2026-09-30 18:00:00.000000

29-STEPS-004-005-INVENTORIES.md Part B4. Both tables are written by
entry-point-inventory and replaced wholesale per repository on rescan.

entry_points.id is derived (sha256 over repository, project, kind, handler,
route and verb, truncated) rather than generated, so it is stable across
rescans. `unauthorised` is an addition to Part B4's column list, kept as a
column so the per-project unauthorised count is a plain query.

entry_point_scans mirrors fingerprint_scans: one row per repository with the
summaries the rows cannot carry (skipped projects, project-wide
authorisation, conventional route tables).

Derived data only, so the downgrade simply drops both tables; a rescan
recreates them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f3a9c2d7e104'
down_revision: Union[str, None] = 'e8b3c61f0a94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KINDS = (
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


def upgrade() -> None:
    op.create_table(
        "entry_points",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("handler_type", sa.Text(), nullable=False),
        sa.Column("handler_member", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=False),
        sa.Column("line_end", sa.Integer(), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("confidence_reasons", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("unauthorised", sa.Boolean(), nullable=True),
        sa.Column("step_execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"kind IN {_KINDS}", name="ck_entry_points_kind"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_entry_points_confidence"),
    )
    op.create_index("ix_entry_points_project_id_kind", "entry_points", ["project_id", "kind"])
    op.create_index("ix_entry_points_repository_id_kind", "entry_points", ["repository_id", "kind"])

    op.create_table(
        "entry_point_scans",
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("scanner_version", sa.Text(), nullable=False),
        sa.Column("skip_source", sa.Text(), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column("project_summaries", postgresql.JSONB(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(), nullable=True),
        sa.Column("step_execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("entry_point_scans")
    op.drop_index("ix_entry_points_repository_id_kind", table_name="entry_points")
    op.drop_index("ix_entry_points_project_id_kind", table_name="entry_points")
    op.drop_table("entry_points")
