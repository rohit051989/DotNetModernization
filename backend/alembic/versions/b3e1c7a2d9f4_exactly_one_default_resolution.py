"""exactly one default resolution per active item

Revision ID: b3e1c7a2d9f4
Revises: a7d4e2c9b1f3
Create Date: 2026-10-08

uq_item_resolutions_one_default guarantees at most one live default per
item, so an item could have none: aspnet-webforms and ssis-package did, and
anything reading "the default" (impact-analysis, the presumptive choice) had
nothing to read. This adds the other half: a constraint trigger, deferred to
commit so a default can move between rows inside one transaction, raising
when an active, live item with any live, active resolution does not have
exactly one live default, or its default is not active.

Checked per touched item, at commit, from item_resolutions (insert, update,
delete) and catalog_items (update: restoring or reactivating an item).
Creating the trigger does not check existing rows. The catalog seed sets the
two missing defaults (factory defaults in app/items/pattern_migration.py),
and `python -m app.items.catalog_seed --check-defaults` lists any active
item without exactly one. No catalog row is written here (CLAUDE.md rule 10).
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b3e1c7a2d9f4'
down_revision: Union[str, None] = 'a7d4e2c9b1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FUNCTION = r"""
CREATE FUNCTION check_item_one_default() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE
    target TEXT;
    live INT;
    defaults INT;
    inactive_defaults INT;
BEGIN
    IF TG_TABLE_NAME = 'catalog_items' THEN
        target := NEW.id;
    ELSIF TG_OP = 'DELETE' THEN
        target := OLD.item_id;
    ELSE
        target := NEW.item_id;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM catalog_items WHERE id = target AND deleted_at IS NULL AND status = 'active') THEN
        RETURN NULL;
    END IF;
    SELECT count(*) FILTER (WHERE status = 'active'),
           count(*) FILTER (WHERE is_default),
           count(*) FILTER (WHERE is_default AND status <> 'active')
      INTO live, defaults, inactive_defaults
      FROM item_resolutions WHERE item_id = target AND deleted_at IS NULL;
    IF live > 0 AND (defaults <> 1 OR inactive_defaults > 0) THEN
        RAISE EXCEPTION 'item % must have exactly one live, active default resolution (has % default(s), % not active)',
            target, defaults, inactive_defaults
            USING ERRCODE = 'check_violation', CONSTRAINT = 'ck_item_resolutions_one_default';
    END IF;
    RETURN NULL;
END
$fn$;
"""


def upgrade() -> None:
    op.execute(FUNCTION)
    op.execute("""
        CREATE CONSTRAINT TRIGGER trg_item_resolutions_one_default
        AFTER INSERT OR UPDATE OR DELETE ON item_resolutions
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_item_one_default()
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER trg_catalog_items_one_default
        AFTER UPDATE ON catalog_items
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_item_one_default()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_catalog_items_one_default ON catalog_items")
    op.execute("DROP TRIGGER trg_item_resolutions_one_default ON item_resolutions")
    op.execute("DROP FUNCTION check_item_one_default()")
