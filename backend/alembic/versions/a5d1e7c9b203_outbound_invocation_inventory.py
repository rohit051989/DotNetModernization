"""step 5 outbound-invocation inventory: outbound_invocations and outbound_scans

Revision ID: a5d1e7c9b203
Revises: c2f7a9d3e815
Create Date: 2026-10-01 12:00:00.000000

29-STEPS-004-005-INVENTORIES.md Part C8. Both tables are written by
outbound-invocation-inventory and replaced wholesale per repository on rescan.

outbound_invocations.id is derived (sha256 over repository, project,
mechanism, normalised endpoint and contract, truncated), so it is stable
across rescans. The endpoint is stored normalised — scheme, host, port,
path — and userinfo, query and fragment never reach this table (Part C5).
credentials holds kind and key path only, never a value. endpoint_host is
indexed: it is what step 10's endpoint register aggregates on.

outbound_scans mirrors entry_point_scans: one row per repository with the
per-project summaries, skipped projects included.

Derived data only, so the downgrade simply drops both tables; a rescan
recreates them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a5d1e7c9b203'
down_revision: Union[str, None] = 'c2f7a9d3e815'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MECHANISMS = ("http_client", "soap_client", "grpc_client", "database", "message_producer", "message_consumer",
              "cache", "secret_store", "file_share", "smtp", "ldap")
VERDICTS = ("incompatible", "requires_change", "unknown", "compatible")
RESOLUTIONS = ("resolved", "partial", "unresolved")
AUTH_DECLARED = ("declared", "none_declared", "not_assessed")


def _in(values):
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.create_table(
        "outbound_invocations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mechanism", sa.Text(), nullable=False),
        sa.Column("endpoint_scheme", sa.Text()),
        sa.Column("endpoint_host", sa.Text()),
        sa.Column("endpoint_port", sa.Integer()),
        sa.Column("endpoint_path", sa.Text()),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("placeholder", sa.Text()),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.Column("environment_bindings", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("call_sites", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("credentials", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("auth_declared", sa.Text()),
        sa.Column("linux_verdict", sa.Text(), nullable=False),
        sa.Column("linux_reasons", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("confidence_reasons", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("step_execution_id", postgresql.UUID(as_uuid=True)),
        sa.Column("detected_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(f"mechanism IN {_in(MECHANISMS)}", name="ck_outbound_invocations_mechanism"),
        sa.CheckConstraint(f"linux_verdict IN {_in(VERDICTS)}", name="ck_outbound_invocations_linux_verdict"),
        sa.CheckConstraint(f"resolution IN {_in(RESOLUTIONS)}", name="ck_outbound_invocations_resolution"),
        sa.CheckConstraint(f"auth_declared IS NULL OR auth_declared IN {_in(AUTH_DECLARED)}", name="ck_outbound_invocations_auth_declared"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_outbound_invocations_confidence"),
    )
    op.create_index("ix_outbound_invocations_repository_id_mechanism", "outbound_invocations", ["repository_id", "mechanism"])
    op.create_index("ix_outbound_invocations_endpoint_host", "outbound_invocations", ["endpoint_host"])
    op.create_index("ix_outbound_invocations_linux_verdict", "outbound_invocations", ["linux_verdict"])

    op.create_table(
        "outbound_scans",
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("scanner_version", sa.Text(), nullable=False),
        sa.Column("skip_source", sa.Text(), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column("project_summaries", postgresql.JSONB(), nullable=False),
        sa.Column("warnings", postgresql.JSONB()),
        sa.Column("step_execution_id", postgresql.UUID(as_uuid=True)),
        sa.Column("scanned_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("outbound_scans")
    op.drop_index("ix_outbound_invocations_linux_verdict", table_name="outbound_invocations")
    op.drop_index("ix_outbound_invocations_endpoint_host", table_name="outbound_invocations")
    op.drop_index("ix_outbound_invocations_repository_id_mechanism", table_name="outbound_invocations")
    op.drop_table("outbound_invocations")
