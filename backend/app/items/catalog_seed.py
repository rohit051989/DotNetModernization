"""The item catalog's factory defaults, seeded on their own — no engagement
data (decisions, scope rows) is read or written.

The database is authoritative for the catalog (app/items/baseline.py). This
applies, in dependency order, every catalog default the full seed applies:
migrated items and resolutions (pattern tables + amendments), authored items
and resolutions (catalog_items.yaml), then resolution derivations. A row
edited since it was seeded is never overwritten; where the default changed
too, a conflict is reported with both versions and the database row stands.

    python -m app.items.catalog_seed                   # apply
    python -m app.items.catalog_seed --dry-run         # report, write nothing
    python -m app.items.catalog_seed --check-defaults  # list active items without exactly one default

Every active item has exactly one default resolution (app/items/defaults.py);
the seed checks it before committing.

`python -m app.seed` does the same as part of the full seed, which also
migrates pattern decisions and repoints decisions off replaced items.
"""

import argparse

from sqlalchemy.orm import Session

from app import models
from app.db import SessionLocal
from app.items import baseline, defaults, derivations, pattern_migration


def seed(db: Session) -> dict:
    """Flushes; the caller commits (or rolls back for a dry run)."""
    from app.seed.seed_data import _load, upsert_authored_item  # the seeder imports this package

    report = baseline.new_report()
    pattern_migration.migrate_catalog(db, report)
    registered = {row.name: row.evidence_kind for row in db.query(models.SignalRegistryEntry)}
    for data in _load("catalog_items.yaml")["items"]:
        upsert_authored_item(db, data, registered, report)
    derivations.apply(db, report)
    defaults.check(db, "catalog seed")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the item catalog's factory defaults; never overwrites an edited row.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change and write nothing.")
    parser.add_argument("--check-defaults", action="store_true",
                        help="List active items without exactly one default resolution; write nothing.")
    args = parser.parse_args()
    db = SessionLocal()
    if args.check_defaults:
        try:
            found = defaults.violations(db)
            print(f"{len(found)} active item(s) without exactly one default resolution")
            for violation in found:
                print("  " + defaults.describe(violation))
            raise SystemExit(1 if found else 0)
        finally:
            db.close()
    try:
        report = seed(db)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
        print(("Would apply: " if args.dry_run else "Applied: ") + baseline.summary(report))
        for key in ("inserted", "updated", "kept_edits"):
            for label in report[key]:
                print(f"  {key}: {label}")
        if report["conflicts"]:
            print(baseline.format_conflicts(report["conflicts"]))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
