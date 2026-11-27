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

# Items a release added to: a resolution, or wording for signals it now detects. Applied from the export the same way
# (baseline.seed_row): a new resolution is inserted, an unedited row takes the new wording, an edited one is reported
# as a conflict and left as it is. datetime-now-usage: the utc-everywhere resolution, and the related forms detected.
# windows-only-assembly-reference (2026-11-24): a new item, raised from dependency-hierarchy's assembly references.
# legacy-project-format and packages-config (2026-11-24): new items, from solution-discovery's project metadata.
# event-log-usage and backslash-path-building (2026-11-25): new items, from registry 1.16.0's signals.
# linq-to-sql-usage, system-web-in-library, wif-usage and windows-workflow-usage (2026-11-26): new items, from registry
# 1.17.0's signals; and detection changes: directory-services-usage locates the signed-in user's checks, fx-aspnet-mvc
# needs an application, missing-dockerfile and missing-ocp4-manifests also match a .NET Framework application; and
# missing-health-endpoint a .NET Framework web application, with the manifests' probes on its paths.
CATALOG_ADDITIONS = ("datetime-now-usage", "windows-only-assembly-reference", "legacy-project-format", "packages-config",
                     "event-log-usage", "backslash-path-building",
                     "linq-to-sql-usage", "system-web-in-library", "wif-usage", "windows-workflow-usage",
                     "directory-services-usage", "fx-aspnet-mvc", "missing-dockerfile", "missing-ocp4-manifests",
                     "missing-health-endpoint")


def guidance_items(files: dict[str, str]) -> tuple[str, ...]:
    """Items a release wrote engine guidance for, or whose resolutions it did (engine_guidance.yaml): applied from the
    export like the additions above, so an installation whose catalog is its database's own takes the new text where a
    row is unedited, and keeps (and reports) a row an admin edited."""
    written = baseline._engine_guidance()
    return tuple(sorted(name[:-len(".yaml")] for name in files if name[:-len(".yaml")] in written))


def phase_items(files: dict[str, str]) -> tuple[str, ...]:
    """Items whose export gives a resolution a phase (36-COPILOT-ENHANCED-CONVERSION "Phases", 2026-11-25): applied from
    the export like the additions above, so an unedited resolution takes its phase and an edited one is reported as a
    conflict and left as it is (rule 10)."""
    import yaml

    return tuple(sorted(name[:-len(".yaml")] for name, text in files.items()
                        if any(r.get("phase") for r in (yaml.safe_load(text) or {}).get("resolutions") or [])))


def design_flag_items(files: dict[str, str]) -> tuple[str, ...]:
    """Items a release flagged a resolution of, "Confirm the design before implementing" (confirm_design, 2026-11-24;
    36-COPILOT-ENHANCED-CONVERSION "Design questions before converting"): the items whose export holds a resolution
    seed/data/confirm_design.yaml lists. Applied from the export like the additions above: an unedited resolution takes
    the flag, an edited one is reported as a conflict and left as it is."""
    import yaml

    flagged = baseline._confirm_design()
    return tuple(sorted(name[:-len(".yaml")] for name, text in files.items()
                        if any(r.get("id") in flagged for r in (yaml.safe_load(text) or {}).get("resolutions") or [])))


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
            report["design_items"] = design_flag_items(files)
            report["guidance_items"] = guidance_items(files)
            report["phase_items"] = phase_items(files)
            corrected = {f"{item}.yaml": files[f"{item}.yaml"]
                         for item in dict.fromkeys(WORDING_CORRECTIONS + CATALOG_ADDITIONS + report["design_items"]
                                                   + report["guidance_items"] + report["phase_items"])
                         if f"{item}.yaml" in files}
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
            print(f"  wording corrections and additions ({', '.join(WORDING_CORRECTIONS + CATALOG_ADDITIONS)}), and the "
                  f"{len(report.get('design_items') or ())} item(s) with a resolution flagged \"confirm the design before "
                  f"implementing\", the {len(report.get('guidance_items') or ())} item(s) with engine guidance, and the "
                  f"{len(report.get('phase_items') or ())} item(s) whose resolutions have a phase: {baseline.summary(corrections)}")
            if corrections["conflicts"]:
                print(baseline.format_conflicts(corrections["conflicts"]))
    engagement = report["engagement"]
    print(f"  engagement data following the catalog: {engagement['decisions']} legacy decision(s) migrated, "
          f"{engagement['scope_rows']} scope row(s), {len(engagement['repointed_decisions'])} decision(s) repointed")
