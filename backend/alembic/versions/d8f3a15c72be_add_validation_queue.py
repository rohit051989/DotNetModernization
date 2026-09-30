"""add the generic validation_queue

Revision ID: d8f3a15c72be
Revises: c2b5e83f91a7
Create Date: 2026-09-23 09:10:00.000000

27-STEP-006-PATTERN-VALIDATION.md Part B.

**Shared gate infrastructure, not step 6 scaffolding.** One queue serves
all four human gates — step 6 (pattern validation), 22 (plan approval),
38 (code review), 50 (release approval). The item *type* varies; the
lifecycle — open, decided, superseded, withdrawn — does not. Four bespoke
queues would mean four notification paths, four "what is waiting on me"
views and four sets of bugs; step 22 should inherit a working surface
rather than build one.

Nothing in this table is step-6 specific. `item_type` and `payload` carry
everything that is.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision: str = 'd8f3a15c72be'
down_revision: Union[str, None] = 'c2b5e83f91a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "validation_queue",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "engagement_id",
            sa.Text(),
            sa.ForeignKey("engagements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The execution that raised it. An item outlives the execution that
        # raised it — that is the whole point of a gate — so this is
        # provenance, not ownership.
        sa.Column(
            "job_execution_id",
            UUID(as_uuid=True),
            sa.ForeignKey("wf_job_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "step_execution_id",
            UUID(as_uuid=True),
            sa.ForeignKey("wf_step_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_name", sa.Text(), nullable=False),
        sa.Column("item_type", sa.Text(), nullable=False),
        # Natural key of the subject — the cluster_id for step 6. This is
        # what makes a re-run idempotent: it finds the existing open item
        # rather than raising a duplicate.
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("outcome", sa.Text()),
        sa.Column("outcome_detail", JSONB()),
        sa.Column("decision_note", sa.Text()),
        sa.Column("decided_by", sa.Text()),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        # Defer (Part C). The item stays `open` — the subject still needs an
        # answer — but is set aside until the evidence improves. Either
        # threshold alone is enough to resurface it.
        sa.Column("deferred_at", sa.DateTime(timezone=True)),
        sa.Column("deferred_until_coverage", sa.Numeric(4, 3)),
        sa.Column("deferred_until_member_count", sa.Integer()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "item_type IN ('pattern_candidate', 'target_state_selection', 'migration_plan', "
            "'code_review', 'release_approval')",
            name="ck_validation_queue_item_type",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'decided', 'superseded', 'withdrawn')",
            name="ck_validation_queue_status",
        ),
        # A decided item owes an answer and a timestamp. Without this a
        # half-written decision looks like a real one to the step that
        # applies it.
        sa.CheckConstraint(
            "status <> 'decided' OR (outcome IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_validation_queue_decided_has_outcome",
        ),
        # A deferral has to say what it is waiting for, or nothing can ever
        # resurface it and `defer` becomes an indefinite silence.
        sa.CheckConstraint(
            "deferred_at IS NULL OR deferred_until_coverage IS NOT NULL "
            "OR deferred_until_member_count IS NOT NULL",
            name="ck_validation_queue_defer_has_threshold",
        ),
    )

    # Part B: one open item per subject. Partial, so the history of decided,
    # superseded and withdrawn items for the same subject accumulates freely
    # — which is what makes a re-review trail readable.
    op.create_index(
        "uq_validation_queue_open_item",
        "validation_queue",
        ["engagement_id", "step_name", "item_key"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index("ix_validation_queue_engagement_status", "validation_queue", ["engagement_id", "status"])
    op.create_index("ix_validation_queue_job_execution", "validation_queue", ["job_execution_id"])
    op.create_index("ix_validation_queue_status_priority", "validation_queue", ["status", "priority"])


def downgrade() -> None:
    op.drop_table("validation_queue")
