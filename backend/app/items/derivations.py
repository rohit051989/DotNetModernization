"""Resolution derivations — 28-ITEM-AND-CONVERSION-MODEL.md Part U.

Loads the `derivations` declared beside each resolution in catalog_items.yaml
into `resolution_derivations` (master catalog data; app/items/coupling.py
reads it). A delivery team adding a resolution to a leading item declares
what it means for each dependent here, as data:

    resolutions:
      - id: wcf-service-rest-rewrite
        ...
        derivations:
          - item: wcf-nettcp-client
            action: derive                     # derive | not_derived | subsume | not_subsumed
            resolution: migrate-to-service-protocol   # derive only
            applies_to: internal_clients       # optional; default all
            reason: "Why, in one sentence: shown on the derived decision and the work list."

Validation is a hard error, so a gap cannot reach the database:
- the dependent item, and a derive's resolution on it, must exist;
- a derive names a resolution, every other action names none;
- **completeness**: every live resolution of a leading item declares a row
  for every dependent any of its resolutions names. A new resolution that
  forgets the host or the clients fails the seed instead of silently
  deriving nothing.

Idempotent, and the database is authoritative (app/items/baseline.py): the
YAML is a factory default. A row not edited since it was seeded follows the
file — updated, soft-deleted when no longer authored (never hard-deleted),
restored when authored again; a row edited since is never overwritten, and
a change on both sides is reported as a conflict.

    python -m app.items.derivations             # apply
    python -m app.items.derivations --dry-run   # report, write nothing
"""

import argparse

from sqlalchemy.orm import Session

from app import models
from app.db import SessionLocal
from app.items import baseline

ACTIONS = models.DERIVATION_ACTIONS
APPLIES_TO = models.DERIVATION_APPLIES_TO
APPLIED_BY = "derivations"


def authored() -> list[dict]:
    """Every derivation in catalog_items.yaml, as flat rows."""
    from app.seed.seed_data import _load  # the seeder imports this module

    rows = []
    for item in _load("catalog_items.yaml")["items"]:
        for resolution in item.get("resolutions", []):
            for entry in resolution.get("derivations", []):
                rows.append({
                    "item_id": item["id"], "resolution_id": resolution["id"], "dependent_item_id": entry["item"],
                    "action": entry["action"], "dependent_resolution_id": entry.get("resolution"),
                    "applies_to": entry.get("applies_to", "all"), "reason": entry["reason"],
                })
    return rows


def validate(db: Session, rows: list[dict]) -> list[str]:
    problems = []
    seen = set()
    for row in rows:
        where = f"{row['resolution_id']} -> {row['dependent_item_id']}"
        key = (row["resolution_id"], row["dependent_item_id"])
        if key in seen:
            problems.append(f"{where}: declared twice")
        seen.add(key)
        if row["action"] not in ACTIONS:
            problems.append(f"{where}: action '{row['action']}' is not one of {', '.join(ACTIONS)}")
        if row["applies_to"] not in APPLIES_TO:
            problems.append(f"{where}: applies_to '{row['applies_to']}' is not one of {', '.join(APPLIES_TO)}")
        if row["dependent_item_id"] == row["item_id"]:
            problems.append(f"{where}: an item cannot depend on itself")
        if not (row.get("reason") or "").strip():
            problems.append(f"{where}: a reason is required")
        dependent = db.get(models.CatalogItem, row["dependent_item_id"])
        if dependent is None or dependent.deleted_at is not None:
            problems.append(f"{where}: no catalog item '{row['dependent_item_id']}'")
        if row["action"] == "derive":
            resolution = db.get(models.ItemResolution, row["dependent_resolution_id"] or "")
            if resolution is None or resolution.deleted_at is not None:
                problems.append(f"{where}: derive needs a resolution of '{row['dependent_item_id']}'; "
                                f"'{row['dependent_resolution_id']}' does not exist")
            elif resolution.item_id != row["dependent_item_id"]:
                problems.append(f"{where}: resolution '{resolution.id}' belongs to '{resolution.item_id}'")
        elif row["dependent_resolution_id"]:
            problems.append(f"{where}: only derive names a resolution ({row['action']} does not)")

    # Completeness, per leading item.
    by_leader: dict[str, list[dict]] = {}
    for row in rows:
        by_leader.setdefault(row["item_id"], []).append(row)
    for leader_item_id, leader_rows in sorted(by_leader.items()):
        dependents = {r["dependent_item_id"] for r in leader_rows}
        menu = db.query(models.ItemResolution).filter(
            models.ItemResolution.item_id == leader_item_id, models.ItemResolution.deleted_at.is_(None),
            models.ItemResolution.status == "active")
        for resolution in sorted(menu, key=lambda r: r.id):
            declared = {r["dependent_item_id"] for r in leader_rows if r["resolution_id"] == resolution.id}
            for missing in sorted(dependents - declared):
                problems.append(f"{resolution.id}: declares nothing for '{missing}', which other {leader_item_id} "
                                "resolutions do — declare derive, not_derived, subsume or not_subsumed")
    return problems


def apply(db: Session, report: dict | None = None) -> dict:
    """Seeds the authored rows through the baseline (app/items/baseline.py):
    missing rows inserted, rows not edited since seeding brought to their
    factory default — including soft-deleting a row no longer authored — and
    an edited row never overwritten, a conflict reported. Raises ValueError
    listing every authoring problem. Flushes; the caller commits."""
    rows = authored()
    problems = validate(db, rows)
    if problems:
        raise ValueError("Resolution derivations are invalid:\n  " + "\n  ".join(problems))
    report = report if report is not None else baseline.new_report()
    keys = set()
    for data in rows:
        key = {"resolution_id": data["resolution_id"], "dependent_item_id": data["dependent_item_id"]}
        keys.add((data["resolution_id"], data["dependent_item_id"]))
        desired = {field: data[field] for field in ("item_id", "action", "dependent_resolution_id", "applies_to", "reason")}
        baseline.seed_row(db, models.ResolutionDerivation, key, {**desired, "deleted": False}, report)
    db.flush()
    for row in db.query(models.ResolutionDerivation).filter(models.ResolutionDerivation.deleted_at.is_(None)).order_by(
            models.ResolutionDerivation.resolution_id, models.ResolutionDerivation.dependent_item_id):
        if (row.resolution_id, row.dependent_item_id) not in keys:
            desired = {**baseline.content(row), "deleted": True, "_deleted_by": f"{APPLIED_BY}: no longer authored"}
            baseline.seed_row(db, models.ResolutionDerivation,
                              {"resolution_id": row.resolution_id, "dependent_item_id": row.dependent_item_id}, desired, report)
    db.flush()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Load resolution derivations from catalog_items.yaml (idempotent).")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change and write nothing.")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        report = apply(db)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
        print(("Would apply: " if args.dry_run else "Applied: ") + baseline.summary(report))
        if report["conflicts"]:
            print(baseline.format_conflicts(report["conflicts"]))
    finally:
        db.close()


if __name__ == "__main__":
    main()
