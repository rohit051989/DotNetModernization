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
import functools
import hashlib
import json
from pathlib import Path

import yaml

from sqlalchemy.orm import Session

from app import models

# The authored content of each table: what a person edits, and what the
# seed writes. "deleted" is whether the row is soft-deleted (deleted_at set).
CONTENT_FIELDS: dict[type, tuple[str, ...]] = {
    models.CatalogItem: ("name", "description", "scope", "category", "detection", "excluded_roles", "owner_team", "status",
                         "deleted", "engine_guidance"),
    models.ItemResolution: ("item_id", "name", "description", "target_description", "consumer_impact", "effort", "is_default",
                            "linux_compatible", "container_ready", "notes", "status", "deleted", "impact_rules",
                            "engine_guidance", "confirm_design", "phase"),
    models.ResolutionDerivation: ("item_id", "action", "dependent_resolution_id", "applies_to", "reason", "deleted"),
}

# Content fields added after baselines were first recorded. Absent and empty
# are the same content: an empty one is left out of content() and of the hash,
# so every row without it keeps its baseline and exports unchanged. A seed or
# import may omit it; omitted means empty.
OPTIONAL_FIELDS: dict[type, dict[str, object]] = {
    models.CatalogItem: {"engine_guidance": None},                            # 36-COPILOT-ENHANCED-CONVERSION Part K
    # 33-IMPACT-ANALYSIS Part D; 36 Part K; 36 "Design questions before converting" (unset is false).
    # 36 "Phases" (unset is null).
    models.ItemResolution: {"impact_rules": [], "engine_guidance": None, "confirm_design": False, "phase": None},
}

ENGINE_GUIDANCE_FILE = Path(__file__).resolve().parents[1] / "seed" / "data" / "engine_guidance.yaml"
# The factory resolutions that change the design or the architecture: confirm_design set (36-COPILOT-ENHANCED-CONVERSION
# "Design questions before converting").
CONFIRM_DESIGN_FILE = Path(__file__).resolve().parents[1] / "seed" / "data" / "confirm_design.yaml"
# The phase of each factory resolution (36-COPILOT-ENHANCED-CONVERSION "Phases"): by item, with overrides by resolution.
PHASES_FILE = Path(__file__).resolve().parents[1] / "seed" / "data" / "phases.yaml"


@functools.cache
def _phases() -> dict:
    return yaml.safe_load(PHASES_FILE.read_text(encoding="utf-8"))


def factory_phase(item_id: str, resolution_id: str) -> int | None:
    """The factory phase of a resolution: its own entry in phases.yaml, else its item's, else None."""
    data = _phases()
    return (data.get("resolutions") or {}).get(resolution_id) or (data.get("items") or {}).get(item_id)


@functools.cache
def _confirm_design() -> frozenset[str]:
    return frozenset(yaml.safe_load(CONFIRM_DESIGN_FILE.read_text(encoding="utf-8"))["resolutions"])


@functools.cache
def _engine_guidance() -> dict:
    """engine_guidance.yaml's items, with the shared text for resolutions that keep something unchanged (its
    `unchanged` section) put in each listed resolution's guidance with that resolution's reason."""
    data = yaml.safe_load(ENGINE_GUIDANCE_FILE.read_text(encoding="utf-8"))
    items = data["items"]
    unchanged = data.get("unchanged") or {}
    for item_id, reasons in (unchanged.get("resolutions") or {}).items():
        resolutions = items.setdefault(item_id, {}).setdefault("resolutions", {})
        for resolution_id, reason in reasons.items():
            if resolution_id in resolutions:
                raise ValueError(f"engine_guidance.yaml: {item_id}/{resolution_id} has its own text and the shared one")
            resolutions[resolution_id] = unchanged["text"].strip().format(reason=reason)
    return items


def engine_guidance() -> dict:
    """{item id: {"guidance": text, "resolutions": {resolution id: text}}}: the factory engine guidance, as seeded."""
    return _engine_guidance()


def with_engine_guidance(model: type, row_id: str, desired: dict, item_id: str | None = None) -> dict:
    """A factory default with its engine-facing guidance from engine_guidance.yaml, when one is written, and for a
    resolution whether it changes the design (confirm_design.yaml). For the factory seeds only (authored items, migrated
    items): an import carries its own."""
    if model is models.CatalogItem:
        text = (_engine_guidance().get(row_id) or {}).get("guidance")
        return {**desired, "engine_guidance": text.strip() if text else None}
    text = ((_engine_guidance().get(item_id or desired["item_id"]) or {}).get("resolutions") or {}).get(row_id)
    item_id = item_id or desired["item_id"]
    return {**desired, "engine_guidance": text.strip() if text else None, "confirm_design": row_id in _confirm_design(),
            "phase": factory_phase(item_id, row_id)}

TABLES = {models.CatalogItem: "catalog_items", models.ItemResolution: "item_resolutions",
          models.ResolutionDerivation: "resolution_derivations"}


def content(row) -> dict:
    fields = CONTENT_FIELDS[type(row)]
    values = {f: (row.deleted_at is not None) if f == "deleted" else getattr(row, f) for f in fields}
    return _without_empty_optional(type(row), values)


def _without_empty_optional(model: type, values: dict) -> dict:
    optional = OPTIONAL_FIELDS.get(model, {})
    return {k: v for k, v in values.items() if not (k in optional and (v is None or v == optional[k]))}


def digest(values: dict) -> str:
    """Deterministic: sorted keys, no whitespace variance."""
    hashed = {k: v for k, v in values.items() if not k.startswith("_")}
    text = json.dumps(hashed, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def values(row) -> dict:
    """Every content field's value, an empty optional one included (content() leaves those out)."""
    fields = CONTENT_FIELDS[type(row)]
    return {f: (row.deleted_at is not None) if f == "deleted" else getattr(row, f) for f in fields}


def field_digest(value) -> str:
    """One field's value, as a field baseline records it."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def field_baseline(row) -> dict | None:
    """{field: digest of the value the seed last wrote} (`seeded_fields`), or, for a row seeded before field baselines
    were recorded, what its whole-row hash tells: every field when the row is unedited; when it was edited, only the
    optional fields still at their empty value, which no edit can have emptied of a value the seed never wrote (a field
    added since, such as a resolution's phase). None: no baseline at all."""
    if row.seeded_fields:
        return dict(row.seeded_fields)
    if row.seeded_hash is None:
        return None
    current = values(row)
    if digest(content(row)) == row.seeded_hash:
        return {f: field_digest(v) for f, v in current.items()}
    optional = OPTIONAL_FIELDS.get(type(row), {})
    return {f: field_digest(v) for f, v in current.items() if f in optional and (v is None or v == optional[f])}


def edit_state(row) -> str:
    """'unedited', 'edited' (a field changed since it was seeded), or 'no_baseline'."""
    if row.seeded_fields:
        base = row.seeded_fields
        return "edited" if any(field_digest(v) != base.get(f) for f, v in values(row).items()) else "unedited"
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
    """Field by field; a field on one side only (an optional one) shows as None on the other."""
    fields = [f for f in current if not f.startswith("_")] + [f for f in desired if f not in current and not f.startswith("_")]
    return {f: {"database": current.get(f), "seed": desired.get(f)} for f in fields if current.get(f) != desired.get(f)}


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
    """Brings one row to its factory default, field by field (rule 10): a field nobody changed since the seed wrote it
    takes the new default, even on a row whose other fields were edited; a field an admin changed is left as it is, and
    reported as a conflict when the default changed too. `key`: primary-key fields. `desired`: every CONTENT_FIELDS
    field; keys starting with "_" (`_deleted_at`, `_deleted_by`) are applied with `deleted` but not compared. Returns
    (row, outcome): inserted, updated (some field written; a conflict on another is reported beside it), unchanged,
    adopted, kept_edit or conflict. Records the row's field baseline (`seeded_fields`). Flushes nothing."""
    optional = OPTIONAL_FIELDS.get(model, {})
    missing = set(CONTENT_FIELDS[model]) - set(desired) - set(optional)
    if missing:
        raise ValueError(f"{TABLES[model]} {key}: desired content lacks {sorted(missing)}")
    # An omitted optional field is its empty value, applied as such, and left out of the whole-row hash like any empty one.
    desired = _without_empty_optional(model, {**optional, **desired})
    applied = {**optional, **desired}
    want = {f: v for f, v in applied.items() if not f.startswith("_")}
    now = datetime.datetime.now(datetime.timezone.utc)
    row = db.get(model, tuple(key.values()) if len(key) > 1 else next(iter(key.values())))
    if row is None:
        row = model(**key)
        if model is models.CatalogItem:
            row.version = 1
        _apply(row, applied, now)
        row.seeded_hash = digest(desired)
        row.seeded_fields = {f: field_digest(v) for f, v in want.items()}
        db.add(row)
        report["inserted"].append(f"{TABLES[model]} {row_label(row)}")
        return row, "inserted"

    label = f"{TABLES[model]} {row_label(row)}"
    current = values(row)
    base = field_baseline(row)
    if base is None and current != want:
        report["conflicts"].append({
            "table": TABLES[model], "row": row_label(row),
            "reason": "no seed baseline (seeded before baselines were recorded, or created in the UI): which side "
                      "changed is unknown",
            "fields": _diff(content(row), {k: v for k, v in desired.items() if not k.startswith("_")}),
        })
        return row, "conflict"
    if base is None:
        row.seeded_hash = digest(desired)
        row.seeded_fields = {f: field_digest(v) for f, v in want.items()}
        report["adopted"].append(label)
        return row, "adopted"

    update, conflicts, kept, unknown = {}, {}, [], False
    recorded = dict(base)
    for field, value in want.items():
        have = current[field]
        if have == value:
            recorded[field] = field_digest(value)
        elif base.get(field) == field_digest(have):
            update[field] = value                               # nobody changed it: the new default
            recorded[field] = field_digest(value)
        elif base.get(field) == field_digest(value):
            kept.append(field)                                  # an admin changed it; the default did not
        else:
            conflicts[field] = {"database": have, "seed": value}  # both changed, or which side is unknown
            unknown = unknown or field not in base
    if update.get("deleted") is True and (conflicts or kept):
        # A row the seed no longer authors is soft-deleted only while nobody has edited it: removing it would undo
        # the edit. The removal is reported instead, with every edited field.
        del update["deleted"]
        recorded["deleted"] = base.get("deleted")
        conflicts.update({f: {"database": current[f], "seed": want[f]} for f in kept})
        conflicts["deleted"] = {"database": current["deleted"], "seed": True}
        kept = []
    if update:
        _apply(row, {**update, **({k: v for k, v in applied.items() if k.startswith("_")} if "deleted" in update else {})},
               now)
    row.seeded_fields = recorded
    if not conflicts and not kept:
        row.seeded_hash = digest(desired)
    if conflicts:
        report["conflicts"].append({
            "table": TABLES[model], "row": row_label(row),
            "reason": ("edited before field baselines were recorded, and the seed's default differs: which side changed "
                       "is unknown" if unknown else "edited since seeding, and the seed's default changed too"),
            "fields": conflicts,
        })
    if update:
        report["updated"].append(label + (f" ({', '.join(sorted(update))}; edited fields kept)" if conflicts or kept else ""))
        return row, "updated"
    if conflicts:
        return row, "conflict"
    if kept:
        report["kept_edits"].append(label)
        return row, "kept_edit"
    return row, "unchanged"


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
