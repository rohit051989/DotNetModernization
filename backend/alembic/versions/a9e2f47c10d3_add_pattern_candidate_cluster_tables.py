"""add pattern_candidate_clusters and pattern_candidate_members

Revision ID: a9e2f47c10d3
Revises: f1b8d6c40a72
Create Date: 2026-09-22 10:15:00.000000

26-STEP-005-PATTERN-DISCOVERY.md Part D. Step 5 groups projects step 4
could not classify into candidate patterns.

Two things about these tables differ from every other step's output and
are deliberate:

1. **Clusters are not replaced wholesale per run.** `cluster_id` derives
   from the shape, so the same shape in a later run resolves to the same
   row and inherits step 6's decision. Upsert, never delete-then-insert.
   `pattern_candidate_members` *is* replaced per cluster per run, since
   membership genuinely is a snapshot.

2. **A cluster whose members all disappear is retained**, with
   `member_count` 0 and `is_stale` true — members disappear for ordinary
   reasons, and when they disappear because the projects finally
   classified, that disappearance is the success. Deleting the row would
   discard the step 6 decision that caused it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision: str = 'a9e2f47c10d3'
down_revision: Union[str, None] = 'f1b8d6c40a72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pattern_candidate_clusters",
        sa.Column("cluster_id", sa.Text(), primary_key=True),
        sa.Column(
            "engagement_id",
            sa.Text(),
            sa.ForeignKey("engagements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cluster_method", sa.Text(), nullable=False),
        sa.Column("canonical_signature", JSONB(), nullable=False),
        sa.Column("signal_count", sa.Integer(), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("repository_count", sa.Integer(), nullable=False),
        sa.Column("repository_distribution", JSONB(), nullable=False),
        sa.Column("cohesion", sa.Numeric(4, 3)),
        sa.Column("is_singleton", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("similar_patterns", JSONB()),
        # Set by step 6, preserved by every subsequent step 5 run.
        sa.Column("status", sa.Text(), nullable=False, server_default="candidate"),
        sa.Column("resolved_pattern_id", sa.Text(), sa.ForeignKey("patterns.id", ondelete="SET NULL")),
        sa.Column("resolution_note", sa.Text()),
        # Decision context: what the human could see when they decided.
        # Step 6 writes these; step 5 reads them to decide re-review.
        sa.Column("decided_at_coverage", sa.Numeric(4, 3)),
        sa.Column("decided_at_member_count", sa.Integer()),
        sa.Column("needs_rereview", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rereview_reason", sa.Text()),
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("step_execution_id", UUID(as_uuid=True)),
        sa.CheckConstraint(
            "cluster_method IN ('exact', 'similarity')",
            name="ck_pattern_candidate_clusters_method",
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'validated_new', 'merged', 'rejected')",
            name="ck_pattern_candidate_clusters_status",
        ),
        # A resolved cluster must record what it was resolved against, or
        # the re-review trigger has no baseline to measure growth from and
        # would either never fire or fire on every run.
        sa.CheckConstraint(
            "status = 'candidate' OR decided_at_member_count IS NOT NULL",
            name="ck_pattern_candidate_clusters_decision_context",
        ),
    )
    op.create_index(
        "ix_pattern_candidate_clusters_engagement",
        "pattern_candidate_clusters",
        ["engagement_id"],
    )
    # Step 6's work queue: undecided clusters, and decided ones whose
    # evidence has since grown enough to be worth another look.
    op.create_index(
        "ix_pattern_candidate_clusters_queue",
        "pattern_candidate_clusters",
        ["engagement_id", "status", "needs_rereview"],
    )

    op.create_table(
        "pattern_candidate_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "cluster_id",
            sa.Text(),
            sa.ForeignKey("pattern_candidate_clusters.cluster_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "repository_id",
            UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("classification_status", sa.Text(), nullable=False),
        sa.Column("similarity_to_signature", sa.Numeric(4, 3)),
        sa.Column("signal_count", sa.Integer(), nullable=False),
        # Lineage per A3: step 5 declares no `consumes` and reads the
        # database directly, so the classification run each member came
        # from is recorded here rather than resolved through an artifact.
        sa.Column("classification_step_execution_id", UUID(as_uuid=True)),
        sa.UniqueConstraint("cluster_id", "project_id", name="uq_pattern_candidate_members_cluster_project"),
    )
    op.create_index("ix_pattern_candidate_members_cluster", "pattern_candidate_members", ["cluster_id"])
    op.create_index("ix_pattern_candidate_members_project", "pattern_candidate_members", ["project_id"])


def downgrade() -> None:
    op.drop_table("pattern_candidate_members")
    op.drop_table("pattern_candidate_clusters")
