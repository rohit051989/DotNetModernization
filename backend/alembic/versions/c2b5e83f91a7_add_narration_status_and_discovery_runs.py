"""add narration columns to clusters and a pattern_discovery_runs table

Revision ID: c2b5e83f91a7
Revises: a9e2f47c10d3
Create Date: 2026-09-22 18:40:00.000000

26-STEP-005-PATTERN-DISCOVERY.md Part E.

Narration failure previously surfaced only as a step diagnostic. At fleet
scale that is easy to miss, and a human arriving at step 6 would see
unnamed clusters with no indication why — which reads as "the platform
has nothing to say about this shape" rather than "the narrator could not
be reached". Those are very different things to act on.

Two additions:

1. Narration lands on the cluster row, not just in the artifact file, so
   step 6 can render a name beside the shape it belongs to without
   parsing a file off disk.

2. `pattern_discovery_runs` records the run-level narration outcome —
   status plus reason — because the interesting fact ("CLI not found") is
   a property of the run, not of any one cluster, and every cluster
   carrying its own copy of it would be both redundant and lossy for the
   disabled case, where there are no narration rows to carry anything.

The run row also stores `output_dir`, which is what lets the retry action
rewrite the narration artifact in place rather than orphaning it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'c2b5e83f91a7'
down_revision: Union[str, None] = 'a9e2f47c10d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-cluster narration. All nullable: a cluster with no narration is
    # the normal state when narration is disabled or unavailable, and is
    # exactly what step 6 renders the signature for instead.
    op.add_column("pattern_candidate_clusters", sa.Column("suggested_name", sa.Text()))
    op.add_column("pattern_candidate_clusters", sa.Column("suggested_description", sa.Text()))
    op.add_column("pattern_candidate_clusters", sa.Column("suggested_pattern_id", sa.Text()))
    op.add_column("pattern_candidate_clusters", sa.Column("narration_confidence", sa.Text()))
    op.add_column(
        "pattern_candidate_clusters",
        sa.Column("naming_source", sa.Text(), nullable=False, server_default="none"),
    )
    op.add_column("pattern_candidate_clusters", sa.Column("narration_model_version", sa.Text()))
    op.add_column("pattern_candidate_clusters", sa.Column("narrated_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_pattern_candidate_clusters_naming_source",
        "pattern_candidate_clusters",
        "naming_source IN ('claude-code', 'human', 'none')",
    )

    op.create_table(
        "pattern_discovery_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "engagement_id",
            sa.Text(),
            sa.ForeignKey("engagements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_execution_id", UUID(as_uuid=True)),
        sa.Column("cluster_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("narrated_cluster_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coverage_ratio", sa.Numeric(4, 3)),
        sa.Column("partial_estate", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("narration_status", sa.Text(), nullable=False),
        # Null only when the status is `succeeded` — every other status owes
        # the human an explanation, which is the entire point of this table.
        sa.Column("narration_reason", sa.Text()),
        sa.Column("output_dir", sa.Text()),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "narration_status IN ('succeeded', 'partial', 'failed', 'disabled')",
            name="ck_pattern_discovery_runs_narration_status",
        ),
        sa.CheckConstraint(
            "narration_status = 'succeeded' OR narration_reason IS NOT NULL",
            name="ck_pattern_discovery_runs_reason_required",
        ),
    )
    op.create_index(
        "ix_pattern_discovery_runs_engagement",
        "pattern_discovery_runs",
        ["engagement_id", "run_at"],
    )


def downgrade() -> None:
    op.drop_table("pattern_discovery_runs")
    op.drop_constraint("ck_pattern_candidate_clusters_naming_source", "pattern_candidate_clusters")
    for column in (
        "narrated_at",
        "narration_model_version",
        "naming_source",
        "narration_confidence",
        "suggested_pattern_id",
        "suggested_description",
        "suggested_name",
    ):
        op.drop_column("pattern_candidate_clusters", column)
