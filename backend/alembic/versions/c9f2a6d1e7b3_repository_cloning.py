"""repository cloning: registering a repository by its git URL

Revision ID: c9f2a6d1e7b3
Revises: b5e1d8c3a904
Create Date: 2026-10-16

A repository registered by URL (source_type git_clone) is cloned by its ingest job: ingest_status 'cloning' while
git runs, and clone_progress carries git's latest progress line for the UI. Existing rows are unchanged: the check
constraint only gains a value, and the column is nullable.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c9f2a6d1e7b3'
down_revision: Union[str, None] = 'b5e1d8c3a904'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('ck_repositories_ingest_status', 'repositories', type_='check')
    op.create_check_constraint(
        'ck_repositories_ingest_status', 'repositories',
        "ingest_status IN ('registered', 'cloning', 'scanned', 'scan_failed', 'path_missing')")
    op.add_column('repositories', sa.Column('clone_progress', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('repositories', 'clone_progress')
    op.execute("UPDATE repositories SET ingest_status = 'scan_failed' WHERE ingest_status = 'cloning'")
    op.drop_constraint('ck_repositories_ingest_status', 'repositories', type_='check')
    op.create_check_constraint(
        'ck_repositories_ingest_status', 'repositories',
        "ingest_status IN ('registered', 'scanned', 'scan_failed', 'path_missing')")
