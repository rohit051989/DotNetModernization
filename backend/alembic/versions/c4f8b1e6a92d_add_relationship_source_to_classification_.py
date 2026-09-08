"""add relationship_source to classification_matches

Revision ID: c4f8b1e6a92d
Revises: e7c4a9b21f36
Create Date: 2026-09-02 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f8b1e6a92d'
down_revision: Union[str, None] = 'e7c4a9b21f36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 24-STEP-004-CLASSIFICATION.md Part E — an undeclared pattern
    # relationship now defaults to CONFLICTING; this records whether a
    # match's conflict/ambiguity outcome came from a declared
    # compatible_with/conflicts_with entry or from that default, so a human
    # can see the outcome came from a default rather than a deliberate
    # catalog decision. Null for a match that never participated in one.
    op.add_column("classification_matches", sa.Column("relationship_source", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_classification_matches_relationship_source",
        "classification_matches",
        "relationship_source IS NULL OR relationship_source IN ('declared', 'defaulted')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_classification_matches_relationship_source", "classification_matches", type_="check")
    op.drop_column("classification_matches", "relationship_source")
