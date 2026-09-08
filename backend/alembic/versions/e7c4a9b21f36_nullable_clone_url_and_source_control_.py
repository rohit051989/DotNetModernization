"""nullable clone_url and source_control_status

Revision ID: e7c4a9b21f36
Revises: b3d6a2f10c47
Create Date: 2026-09-02 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7c4a9b21f36'
down_revision: Union[str, None] = 'b3d6a2f10c47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 15-REPOSITORY-INGEST-UI.md Part C — a folder that was never under
    # source control has no clone_url to assert. Add the column first
    # (default NONE covers existing rows), then backfill from the existing
    # has_git_history column, which already recorded the same fact.
    op.add_column("repositories", sa.Column("source_control_status", sa.Text(), nullable=False, server_default="NONE"))
    op.execute("UPDATE repositories SET source_control_status = 'GIT' WHERE has_git_history = true")
    op.create_check_constraint(
        "ck_repositories_source_control_status",
        "repositories",
        "source_control_status IN ('GIT', 'NONE')",
    )

    op.alter_column("repositories", "clone_url", existing_type=sa.Text(), nullable=True)
    op.alter_column("repositories", "clone_url_normalised", existing_type=sa.Text(), nullable=True)

    # Every existing row was registered under the old clone_url-mandatory
    # rule, so this is a no-op in practice today — it only matters for rows
    # inserted after this migration.
    op.create_check_constraint(
        "ck_repositories_clone_url_required_for_git",
        "repositories",
        "source_control_status != 'GIT' OR clone_url IS NOT NULL",
    )

    op.drop_constraint("ck_repositories_clone_url_verification", "repositories", type_="check")
    op.create_check_constraint(
        "ck_repositories_clone_url_verification",
        "repositories",
        "clone_url_verification IN ('verified', 'mismatch', 'unverifiable', 'not_applicable')",
    )

    # The clone-URL identity check must not apply where there is no
    # clone_url to compare — root_folder_name and local_path_normalised
    # remain the identity checks for non-git folders.
    op.drop_index("uq_repositories_engagement_clone_url_normalised", table_name="repositories", postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index(
        "uq_repositories_engagement_clone_url_normalised",
        "repositories",
        ["engagement_id", "clone_url_normalised"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND clone_url_normalised IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_repositories_engagement_clone_url_normalised", table_name="repositories", postgresql_where=sa.text("deleted_at IS NULL AND clone_url_normalised IS NOT NULL"))
    op.create_index(
        "uq_repositories_engagement_clone_url_normalised",
        "repositories",
        ["engagement_id", "clone_url_normalised"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.drop_constraint("ck_repositories_clone_url_verification", "repositories", type_="check")
    op.create_check_constraint(
        "ck_repositories_clone_url_verification",
        "repositories",
        "clone_url_verification IN ('verified', 'mismatch', 'unverifiable')",
    )

    op.drop_constraint("ck_repositories_clone_url_required_for_git", "repositories", type_="check")

    # Rows with no clone_url would violate NOT NULL — this downgrade is only
    # meant for a database that never used the new nullable state.
    op.alter_column("repositories", "clone_url_normalised", existing_type=sa.Text(), nullable=False)
    op.alter_column("repositories", "clone_url", existing_type=sa.Text(), nullable=False)

    op.drop_constraint("ck_repositories_source_control_status", "repositories", type_="check")
    op.drop_column("repositories", "source_control_status")
