"""catalog change sequence

Revision ID: c7f2a9d41e86
Revises: b4e8c1a73d50
Create Date: 2026-10-06 23:00:00.000000

catalog_change_seq advances on every statement that writes catalog_items,
item_resolutions, resolution_derivations or catalog_exports — from any
process (the API, the seed, the export command) and any writer (ORM, bulk
update, raw SQL). The catalog export staleness status is cached against it
(app/items/catalog_export.py cached_status): a poll reads one number and
recomputes only when it moved. A rolled-back write still advances the
sequence; that only costs one unnecessary recompute.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c7f2a9d41e86'
down_revision: Union[str, None] = 'b4e8c1a73d50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ('catalog_items', 'item_resolutions', 'resolution_derivations', 'catalog_exports')


def upgrade() -> None:
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


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_catalog_change ON {table}")
    op.execute("DROP FUNCTION IF EXISTS bump_catalog_change_seq()")
    op.execute("DROP SEQUENCE IF EXISTS catalog_change_seq")
