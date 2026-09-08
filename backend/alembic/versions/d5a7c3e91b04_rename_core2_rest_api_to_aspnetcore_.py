"""rename core2-rest-api to aspnetcore-rest-api-legacy

Revision ID: d5a7c3e91b04
Revises: c4f8b1e6a92d
Create Date: 2026-09-02 14:00:00.000000

24-STEP-004-CLASSIFICATION.md Part C — "framework family discriminates
patterns, framework version parameterises accelerators". `core2-rest-api`
split a single code shape by minor release; the pattern is the same
Startup.cs + WebHost/Host.CreateDefaultBuilder hosting model whether it is
Core 2.1 or 3.1, so the id loses its version.

A pattern id is the PK behind five FKs, all ON UPDATE NO ACTION, so this
cannot be a bare `UPDATE patterns SET id = ...`. It runs as
insert-new -> repoint-references -> soft-delete-old, which never leaves a
dangling reference. The old row is soft-deleted rather than removed, per
CLAUDE.md's "nothing in the catalog is ever hard-deleted" — it keeps the
retired id resolvable for pre-rename artifacts under backend/runs/ that
still name it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5a7c3e91b04'
down_revision: Union[str, None] = 'c4f8b1e6a92d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_ID = "core2-rest-api"
NEW_ID = "aspnetcore-rest-api-legacy"

# Every FK onto patterns.id, and the column that carries it.
_REFERENCES = [
    ("target_state_options", "pattern_id"),
    ("decision_records", "pattern_id"),
    ("engagement_patterns", "pattern_id"),
    ("classification_matches", "pattern_id"),
    ("project_classifications", "primary_pattern_id"),
]


def _rename(from_id: str, to_id: str, reason: str) -> None:
    conn = op.get_bind()

    exists = conn.execute(
        sa.text("SELECT 1 FROM patterns WHERE id = :from_id"), {"from_id": from_id}
    ).first()
    if exists is None:
        # Fresh database already seeded under the new id — nothing to move.
        return

    # 1. Copy the row under the new id so the FK targets exist before any
    #    reference is repointed. Explicit column lists on both sides — a
    #    positional INSERT ... SELECT would silently depend on the physical
    #    column order of `patterns`. version bumps: renaming an id and
    #    reshaping rules is a material change (Part C).
    conn.execute(
        sa.text(
            """
            INSERT INTO patterns (
                id, name, summary, description, legacy_stack, category,
                detection_rules, typical_indicators, known_risks, status, version,
                created_at, updated_at, deleted_at, deleted_by,
                classification_role, classification_family, classification_value,
                scope, priority, compatible_with, conflicts_with, anchor_signals,
                eligibility, analysis_requirements, thresholds, rules_status,
                required_signals_pending
            )
            SELECT
                :to_id, name, summary, description, legacy_stack, category,
                detection_rules, typical_indicators, known_risks, status, version + 1,
                created_at, now(), NULL, NULL,
                classification_role, classification_family, classification_value,
                scope, priority, compatible_with, conflicts_with, anchor_signals,
                eligibility, analysis_requirements, thresholds, rules_status,
                required_signals_pending
            FROM patterns WHERE id = :from_id
            """
        ),
        {"to_id": to_id, "from_id": from_id},
    )

    # 2. Repoint everything that referenced the old id. Decision records are
    #    the ones that matter — they carry real engagement approvals and must
    #    follow the pattern, not be duplicated against it.
    for table, column in _REFERENCES:
        conn.execute(
            sa.text(f"UPDATE {table} SET {column} = :to_id WHERE {column} = :from_id"),
            {"to_id": to_id, "from_id": from_id},
        )

    # 3. Retire the old row. Soft delete, so nothing is hard-deleted from the
    #    catalog and the retired id still resolves.
    conn.execute(
        sa.text(
            "UPDATE patterns SET deleted_at = now(), deleted_by = :reason, updated_at = now() "
            "WHERE id = :from_id"
        ),
        {"from_id": from_id, "reason": reason},
    )


def upgrade() -> None:
    _rename(OLD_ID, NEW_ID, reason=f"renamed to '{NEW_ID}' (catalog rename migration d5a7c3e91b04)")


def downgrade() -> None:
    # Reverse direction: revive the old row, move references back, retire the new.
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE patterns SET deleted_at = NULL, deleted_by = NULL WHERE id = :old_id"),
        {"old_id": OLD_ID},
    )
    for table, column in _REFERENCES:
        conn.execute(
            sa.text(f"UPDATE {table} SET {column} = :old_id WHERE {column} = :new_id"),
            {"old_id": OLD_ID, "new_id": NEW_ID},
        )
    conn.execute(sa.text("DELETE FROM patterns WHERE id = :new_id"), {"new_id": NEW_ID})
