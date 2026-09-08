"""add fingerprint_signals evidence_kind

Revision ID: b3d6a2f10c47
Revises: 8fa410190b6d
Create Date: 2026-09-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d6a2f10c47'
down_revision: Union[str, None] = '8fa410190b6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 25-STANDARDS-AND-VIEWPOINTS.md Part A3 addendum — what source_path
    # names (a file, a folder, or neither). Nullable: existing rows from
    # before step 3 started stamping this predate the field.
    op.add_column("fingerprint_signals", sa.Column("evidence_kind", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_fingerprint_signals_evidence_kind",
        "fingerprint_signals",
        "evidence_kind IS NULL OR evidence_kind IN ('FILE', 'FOLDER', 'NONE')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_fingerprint_signals_evidence_kind", "fingerprint_signals", type_="check")
    op.drop_column("fingerprint_signals", "evidence_kind")
