"""Seed baselines — the database is authoritative for the catalog.

catalog_items.yaml, the pattern tables the migration reads, and the
amendments in code are **factory defaults**, not a second source of truth.
The catalog is edited in the UI (or the API). So every seed write to
`catalog_items`, `item_resolutions` and `resolution_derivations` goes
through `seed_row` here, which follows one rule: **a reseed never overwrites
a row edited since it was seeded.**

Each row carries `seeded_hash`: a hash of the content the seed last wrote
(`content()`: the authored fields, plus whether the row is soft-deleted).
Comparing the row's current content against it says whether anyone has
changed it since.

| Row | Factory default (desired) | Outcome |
|---|---|---|
| missing | — | inserted, hash recorded |
| equals desired | — | unchanged (hash recorded if it had none: adopted) |
| unedited (current hash = seeded_hash) | differs | updated to desired, hash re-recorded |
| edited | unchanged since seeding (desired hash = seeded_hash) | left as is: the edit stands (`kept_edits`) |
| edited | changed too | left as is, reported as a **conflict** with both versions |
| no baseline (seeded_hash null: before this rule, or created in the UI) | differs | left as is, reported as a conflict — which side changed is unknowable |

Computed columns (readiness `state`, `version`, timestamps) are not
content: the seed and readiness maintain them; they are not edits.
"""

import datetime
import hashlib
import json

from sqlalchemy.orm import Session

from app import models

# The authored content of each table: what a person edits, and what the
# seed writes. "deleted" is whether the row is soft-deleted (deleted_at set).
CONTENT_FIELDS: dict[type, tuple[str, ...]] = {
    models.CatalogItem: ("name", "description", "scope", "category", "detection", "excluded_roles", "owner_team", "status",
                         "deleted"),
    models.ItemResolution: ("item_id", "name", "description", "target_description", "consumer_impact", "effort", "is_default",
                            "linux_compatible", "container_ready", "notes", "status", "deleted"),
    models.ResolutionDerivation: ("item_id", "action", "dependent_resolution_id", "applies_to", "reason", "deleted"),
}

TABLES = {models.CatalogItem: "catalog_items", models.ItemResolution: "item_resolutions",
          models.ResolutionDerivation: "resolution_derivations"}


def content(row) -> dict:
    fields = CONTENT_FIELDS[type(row)]
    return {f: (row.deleted_at is not None) if f == "deleted" else getattr(row, f) for f in fields}


def digest(values: dict) -> str:
    """Deterministic: sorted keys, no whitespace variance."""
    hashed = {k: v for k, v in values.items() if not k.startswith("_")}
    text = json.dumps(hashed, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def edit_state(row) -> str:
    """'unedited', 'edited' (changed since seeded), or 'no_baseline'."""
    if row.seeded_hash is None:
        return "no_baseline"
    return "unedited" if digest(content(row)) == row.seeded_hash else "edited"


def row_label(row) -> str:
    if isinstance(row, models.ResolutionDerivation):
        return f"{row.resolution_id} -> {row.dependent_item_id}"
    return row.id


def new_report() -> dict:
    return {"inserted": [], "updated": [], "adopted": [], "kept_edits": [], "conflicts": []}


def _diff(current: dict, desired: dict) -> dict:
    return {f: {"database": current[f], "seed": desired[f]} for f in current if f in desired and current[f] != desired[f]}


def _apply(row, desired: dict, now: datetime.datetime) -> None:
    for field, value in desired.items():
        if field.startswith("_"):
            continue
        if field == "deleted":
            if value and row.deleted_at is None:
                row.deleted_at = desired.get("_deleted_at") or now
                row.deleted_by = desired.get("_deleted_by") or "seed"
            elif not value and row.deleted_at is not None:
                row.deleted_at = None
                row.deleted_by = None
        else:
            setattr(row, field, value)


def seed_row(db: Session, model: type, key: dict, desired: dict, report: dict) -> tuple[object, str]:
    """Brings one row to its factory default unless it has been edited.
    `key`: primary-key fields. `desired`: every CONTENT_FIELDS field; keys
    starting with "_" (`_deleted_at`, `_deleted_by`) are applied on a write
    but not hashed. Returns (row, outcome): inserted, updated, unchanged,
    adopted, kept_edit or conflict. Flushes nothing; the caller does."""
    missing = set(CONTENT_FIELDS[model]) - set(desired)
    if missing:
        raise ValueError(f"{TABLES[model]} {key}: desired content lacks {sorted(missing)}")
    now = datetime.datetime.now(datetime.timezone.utc)
    row = db.get(model, tuple(key.values()) if len(key) > 1 else next(iter(key.values())))
    if row is None:
        row = model(**key)
        if model is models.CatalogItem:
            row.version = 1
        _apply(row, desired, now)
        row.seeded_hash = digest(desired)
        db.add(row)
        report["inserted"].append(f"{TABLES[model]} {row_label(row)}")
        return row, "inserted"

    label = f"{TABLES[model]} {row_label(row)}"
    current = content(row)
    target = {k: v for k, v in desired.items() if not k.startswith("_")}
    state = edit_state(row)
    if current == target:
        if row.seeded_hash != digest(desired):
            row.seeded_hash = digest(desired)
            if state == "no_baseline":
                report["adopted"].append(label)
                return row, "adopted"
        return row, "unchanged"
    if state == "unedited":
        _apply(row, desired, now)
        row.seeded_hash = digest(desired)
        report["updated"].append(label)
        return row, "updated"
    if state == "edited" and digest(desired) == row.seeded_hash:
        # Only the database changed: the edit stands; nothing to report but that.
        report["kept_edits"].append(label)
        return row, "kept_edit"
    report["conflicts"].append({
        "table": TABLES[model], "row": row_label(row),
        "reason": "edited since seeding, and the seed's default changed too" if state == "edited"
        else "no seed baseline (seeded before baselines were recorded, or created in the UI): which side changed is unknown",
        "fields": _diff(current, target),
    })
    return row, "conflict"


def merge(report: dict, other: dict) -> dict:
    for key in report:
        report[key].extend(other.get(key, []))
    return report


def format_conflicts(conflicts: list[dict]) -> str:
    lines = []
    for conflict in conflicts:
        lines.append(f"  CONFLICT {conflict['table']} {conflict['row']}: {conflict['reason']}. Database row left as it is.")
        for field, versions in conflict["fields"].items():
            lines.append(f"    {field}:")
            lines.append(f"      database: {json.dumps(versions['database'], default=str, ensure_ascii=False)[:400]}")
            lines.append(f"      seed:     {json.dumps(versions['seed'], default=str, ensure_ascii=False)[:400]}")
    return "\n".join(lines)


def summary(report: dict) -> str:
    return (f"{len(report['inserted'])} inserted, {len(report['updated'])} updated, {len(report['adopted'])} adopted, "
            f"{len(report['kept_edits'])} edit(s) kept, {len(report['conflicts'])} conflict(s)")
