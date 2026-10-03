"""step 6 dependency-assessment: package_assessments, package_lookup_cache, engagements.target_framework

Revision ID: c3f9a1d5e724
Revises: b8e2f4a6c917
Create Date: 2026-10-02 10:00:00.000000

30-STEP-006-DEPENDENCY-ASSESSMENT.md Parts C1 and F.

engagements.target_framework is the framework packages must support (Part
C1) — net10.0 by default, which is what TestClientA and TestClientB target.

package_assessments: one row per project per direct package, replaced per
repository on each run. id is derived (sha256 over repository, project and
package id), so it is stable across rescans. Nothing derived from a feed
credential is stored: feed_url is normalised (no userinfo, query or fragment).

package_lookup_cache: what each feed said about each package, keyed by
(feed_url_normalised, package_id), with fetched_at. Not derived from any one
repository and not replaced per run: a rescan reuses entries younger than the
TTL, which is what makes two runs against the same cache identical (Part B6).
Kept by scripts/reset-demo.ps1 for the same reason the catalog is: it is not
client data.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3f9a1d5e724'
down_revision: Union[str, None] = 'b8e2f4a6c917'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OUTCOMES = ("current", "upgrade_safe", "upgrade_breaking", "no_compatible_version", "unknown")


def _in(values):
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.add_column("engagements", sa.Column("target_framework", sa.Text(), nullable=False, server_default="net10.0"))

    op.create_table(
        "package_assessments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_id", sa.Text(), nullable=False),
        sa.Column("current_version", sa.Text()),
        sa.Column("recommended_version", sa.Text()),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("outcome_reason", sa.Text()),
        sa.Column("classification_method", sa.Text()),
        sa.Column("deprecated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deprecation_replacement", sa.Text()),
        sa.Column("vulnerable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("vulnerability_max_severity", sa.Text()),
        sa.Column("vulnerabilities_resolved_by_upgrade", sa.Boolean()),
        sa.Column("not_in_client_feed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latest_public_version", sa.Text()),
        sa.Column("feed_source", sa.Text()),
        sa.Column("feed_name", sa.Text()),
        sa.Column("feed_url", sa.Text()),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("breaking_members", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("call_sites", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("step_execution_id", postgresql.UUID(as_uuid=True)),
        sa.Column("assessed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(f"outcome IN {_in(OUTCOMES)}", name="ck_package_assessments_outcome"),
        sa.CheckConstraint("classification_method IS NULL OR classification_method IN ('api_diff', 'semver_heuristic')", name="ck_package_assessments_method"),
        sa.CheckConstraint("feed_source IS NULL OR feed_source IN ('client_feed', 'nuget_org_fallback')", name="ck_package_assessments_feed_source"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_package_assessments_confidence"),
    )
    op.create_index("ix_package_assessments_repository_id_outcome", "package_assessments", ["repository_id", "outcome"])
    op.create_index("ix_package_assessments_package_id", "package_assessments", ["package_id"])

    op.create_table(
        "package_lookup_cache",
        sa.Column("feed_url_normalised", sa.Text(), primary_key=True),
        sa.Column("package_id", sa.Text(), primary_key=True),
        sa.Column("versions", postgresql.JSONB(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("package_lookup_cache")
    op.drop_index("ix_package_assessments_package_id", table_name="package_assessments")
    op.drop_index("ix_package_assessments_repository_id_outcome", table_name="package_assessments")
    op.drop_table("package_assessments")
    op.drop_column("engagements", "target_framework")
