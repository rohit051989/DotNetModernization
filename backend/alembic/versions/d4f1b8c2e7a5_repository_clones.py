"""repository clones: each person's own clone of a repository, on each of their machines; file locations relative

- repository_clones: where one person's clone of a repository is on one of their machines (local_path), recorded by
  them and checked to be a clone of the same repository (the same remote URL). An editor link joins the viewer's own
  clone with a file's path relative to the repository. One per (repository, person, machine).
- The owner's clone is the folder the repository was registered from: one row for each repository with an owner and
  a registration machine, from repositories.local_path (which is kept: the owner's platform scans it).
- File locations stored as absolute paths inside a repository's folder (older scans) become relative to it, with
  forward slashes, as every scan writes them now. A path outside the folder is left as it is.

Only adds, and rewrites only paths that begin with their repository's own folder.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4f1b8c2e7a5'
down_revision: Union[str, None] = 'c3e8a1d6f4b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column): a file's location, with the table's repository_id.
PATH_COLUMNS = (
    ('entry_points', 'file_path'),
    ('file_impact_rollup', 'file_key'),
    ('fingerprint_signals', 'source_path'),
    ('impact_summaries', 'project_path'),
    ('item_occurrences', 'file_path'),
    ('projects', 'relative_path'),
    ('repository_artifacts', 'relative_path'),
    ('solutions', 'relative_path'),
    ('source_file_coverage', 'file_path'),
    ('source_file_coverage', 'project_path'),
    ('test_classes', 'file_path'),
    ('test_classes', 'project_path'),
    ('test_mappings', 'test_file'),
    ('work_item_impacts', 'file_path'),
    ('work_item_impacts', 'project_path'),
)


def upgrade() -> None:
    op.create_table(
        'repository_clones',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('repositories.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('hostname', sa.Text(), nullable=False),
        sa.Column('local_path', sa.Text(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('uq_repository_clones_person_machine', 'repository_clones',
                    ['repository_id', 'user_id', sa.text('lower(hostname)')], unique=True)

    # The owner's clone: the folder it was registered from, on the machine it was registered on.
    op.execute("""
        INSERT INTO repository_clones (repository_id, user_id, hostname, local_path, recorded_at)
        SELECT id, owner_user_id, registered_host, local_path, coalesce(first_registered_at, created_at)
        FROM repositories
        WHERE owner_user_id IS NOT NULL AND registered_host IS NOT NULL AND local_path <> ''
    """)

    # Absolute paths inside the repository's own folder become relative to it. The folder is compared without regard
    # to case or slash direction, as Windows does; only a path that continues past it with a separator changes.
    for table, column in PATH_COLUMNS:
        op.execute(f"""
            UPDATE {table} AS t
            SET {column} = replace(substr(replace(t.{column}, '\\', '/'),
                                          length(rtrim(replace(r.local_path, '\\', '/'), '/')) + 2), '\\', '/')
            FROM repositories r
            WHERE r.id = t.repository_id
              AND r.local_path <> ''
              AND lower(replace(t.{column}, '\\', '/')) LIKE
                  replace(replace(replace(lower(rtrim(replace(r.local_path, '\\', '/'), '/')), '\\', '\\\\'), '%', '\\%'),
                          '_', '\\_') || '/%'
        """)


def downgrade() -> None:
    op.drop_index('uq_repository_clones_person_machine', table_name='repository_clones')
    op.drop_table('repository_clones')
