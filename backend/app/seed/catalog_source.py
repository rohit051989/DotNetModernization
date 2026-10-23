"""Where a seed takes the item catalog from — 28-ITEM Part W, "Standing up
a new environment".

Catalog edits are made in the UI: they live in the database and, once
exported, in `catalog/items/` — never in the factory YAML. So once an export
exists it, not `catalog_items.yaml`, is the catalog's record in the
repository, and a new environment must come up with it.

| Catalog in the database | Export in the repository | Source |
|---|---|---|
| empty | present | **export**: imported (catalog_export.import_files; every row inserted) |
| not empty | present | **database**: left as it is — the database is authoritative. A stale export would otherwise roll back newer rows; merging an export into a live catalog is the explicit `python -m app.items.catalog_export import` |
| either | absent | **factory**: catalog_items.yaml, the pattern migration and the amendments, through the seed baseline (rule 10) |

Engagement data tied to the catalog — legacy decision records and pattern
overlays migrated onto items, decisions repointed off replaced items — is
brought along in every case; it never writes catalog rows.

`CATALOG_EXPORT_DIR` overrides where the export is read from (the bootstrap
proof uses a scratch export); by default it is the repository's
`catalog/items/`.
"""

import datetime
import os
from pathlib import Path

from app import models
from app.db import SessionLocal
from app.items import architecture_items, baseline, catalog_export, pattern_migration


def export_dir() -> Path:
    return Path(os.environ.get("CATALOG_EXPORT_DIR") or catalog_export.DEFAULT_DIR)


def export_exists() -> bool:
    return export_dir().is_dir() and any(export_dir().glob("*.yaml"))


def choose(db) -> str:
    if not export_exists():
        return "factory"
    if db.query(models.CatalogItem).first() is None:
        return "export"
    return "database"


def _engagement_data(db) -> dict:
    """Engagement rows that follow the catalog; no catalog writes."""
    report = pattern_migration.migrate_engagement_data(db)
    repoint = {"repointed_decisions": [], "moved_scope_rows": 0}
    now = datetime.datetime.now(datetime.timezone.utc)
    for replacement in architecture_items.REPLACEMENTS:
        architecture_items.replace_item(db, replacement, repoint, now)
    db.flush()
    return {**report, **repoint}


# Items whose wording a release corrected because it described a client's findings rather than the pattern (release 7;
# CLAUDE.md rule 18). An existing catalog is the database's own, so a reseed would never bring the correction; these are
# applied from the export through baseline.seed_row, like any seed: a row nobody has edited takes the new wording, and
# an edited one is left as it is and reported as a conflict, for a person to correct.
WORDING_CORRECTIONS = ("serilog-file-sink", "wcf-nettcp-client")


def seed_from_export_or_database() -> dict | None:
    """Runs the export or database source and returns its report, or None
    when the factory defaults apply (the caller runs those, unchanged)."""
    db = SessionLocal()
    try:
        source = choose(db)
        if source == "factory":
            return None
        report = {"source": source, "dir": str(export_dir()), "baseline": baseline.new_report()}
        files = catalog_export.read_files(export_dir())
        if source == "export":
            report["baseline"] = catalog_export.import_files(db, files)
        else:
            corrected = {f"{item}.yaml": files[f"{item}.yaml"] for item in WORDING_CORRECTIONS if f"{item}.yaml" in files}
            report["corrections"] = catalog_export.import_files(db, corrected) if corrected else baseline.new_report()
        # A catalog identical to the committed export, with no export recorded (a fresh install imported it): record
        # it, so staleness reads "current", not "not in git".
        if (export_dir().resolve() == catalog_export.DEFAULT_DIR.resolve()
                and db.query(models.CatalogExport).first() is None
                and catalog_export.export_files(db) == files):
            catalog_export.record_export(db, export_dir(), catalog_export.item_states(db))
            report["recorded_export"] = True
        report["engagement"] = _engagement_data(db)
        db.commit()
        return report
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def print_report(report: dict) -> None:
    if report["source"] == "export":
        print(f"Catalog from the export ({report['dir']}): {baseline.summary(report['baseline'])}")
        if report["baseline"]["conflicts"]:
            print(baseline.format_conflicts(report["baseline"]["conflicts"]))
    else:
        print("Catalog: the database's own — an export exists, so the factory defaults do not apply, and the database is "
              "authoritative over it (merge an export explicitly with python -m app.items.catalog_export import)")
        corrections = report.get("corrections")
        if corrections is not None:
            print(f"  wording corrections ({', '.join(WORDING_CORRECTIONS)}): {baseline.summary(corrections)}")
            if corrections["conflicts"]:
                print(baseline.format_conflicts(corrections["conflicts"]))
    engagement = report["engagement"]
    print(f"  engagement data following the catalog: {engagement['decisions']} legacy decision(s) migrated, "
          f"{engagement['scope_rows']} scope row(s), {len(engagement['repointed_decisions'])} decision(s) repointed")
