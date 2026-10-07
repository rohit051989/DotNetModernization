"""catalog change counter replaces the sequence

Revision ID: d3b8e5f07a29
Revises: c7f2a9d41e86
Create Date: 2026-10-06 23:30:00.000000

c7f2a9d41e86 advanced a sequence from statement triggers. A sequence moves
when the writing statement runs, before its transaction commits, so a poll
in between could cache the status of the uncommitted-and-invisible state
under the new number and keep serving it after the commit. A one-row counter
updated by the same triggers is transactional: the new version becomes
visible atomically with the rows it describes, and a rolled-back write does
not move it. The status cache reads the version before computing, so it can
never hold a stale status under a current version.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd3b8e5f07a29'
down_revision: Union[str, None] = 'c7f2a9d41e86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ('catalog_items', 'item_resolutions', 'resolution_derivations', 'catalog_exports')


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_catalog_change ON {table}")
    op.execute("DROP FUNCTION IF EXISTS bump_catalog_change_seq()")
    op.execute("DROP SEQUENCE IF EXISTS catalog_change_seq")

    op.execute("""
        CREATE TABLE catalog_change_counter (
            id integer PRIMARY KEY CHECK (id = 1),
            version bigint NOT NULL
        )
    """)
    op.execute("INSERT INTO catalog_change_counter (id, version) VALUES (1, 0)")
    op.execute("""
        CREATE FUNCTION bump_catalog_change_counter() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE catalog_change_counter SET version = version + 1 WHERE id = 1;
            RETURN NULL;
        END
        $$
    """)
    for table in TABLES:
        op.execute(f"""
            CREATE TRIGGER {table}_catalog_change
            AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION bump_catalog_change_counter()
        """)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_catalog_change ON {table}")
    op.execute("DROP FUNCTION IF EXISTS bump_catalog_change_counter()")
    op.execute("DROP TABLE IF EXISTS catalog_change_counter")
    op.execute("CREATE SEQUENCE catalog_change_seq")
    op.execute("""
        CREATE FUNCTION bump_catalog_change_seq() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM nextval('catalog_change_seq');
            RETURN NULL;
        END
        $$
    """)
    for table in TABLES:
        op.execute(f"""
            CREATE TRIGGER {table}_catalog_change
            AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION bump_catalog_change_seq()
        """)
