"""Item catalog export — one file per item, for review and history in git.

The database is authoritative for the catalog (app/items/baseline.py,
28-ITEM Part V). This exports `catalog_items`, `item_resolutions` and
`resolution_derivations` as `catalog/items/<item-id>.yaml`: the item, its
resolutions, and each resolution's derivations. One file per item keeps git
diffs small and merge conflicts rare.

**Deterministic.** Keys sorted at every level; resolutions sorted by id,
derivations by dependent item; items in id order; detection exactly as
stored. An unchanged catalog exports byte-identically.

**Content only.** Exactly the baseline content of each row
(baseline.CONTENT_FIELDS): no `seeded_hash`, no computed columns (readiness,
version), no timestamps. A soft-deleted row is exported with
`deleted: true` and its `deleted_by` — a deletion, and why, is a reviewable
change. Engagement data
(decisions, scope) is client data, not catalog content, and never exported.

**Staleness.** Each export into the repository's catalog/items/ is
recorded (catalog_exports) with a hash per item. `status` compares the
database against the last one — which items were added, edited or deleted
since — for the master catalog view and the dashboard, cached against a change
sequence the database advances on every catalog write (`cached_status`), so
a dashboard poll is a cache read. Nothing exports
automatically: writing into the repository from a web request would couple
the running server to the working tree, so a person exports and commits.

**One-way.** The export is for review and history, not a second place to
edit. `import` exists to bootstrap a new environment: onto an empty catalog
it inserts every row; onto a non-empty one it goes through
baseline.seed_row like any seed — inserting missing rows, updating rows not
edited since they were seeded, and reporting a conflict on an edited row,
never overwriting it.

    python -m app.items.catalog_export export [--out DIR]           # default: <repo>/catalog/items
    python -m app.items.catalog_export import [--from DIR] [--dry-run]
    python -m app.items.catalog_export roundtrip                    # export, import into a fresh database, export, compare
"""

import argparse
import hashlib
import io
import os
import subprocess
import sys
import threading
import uuid
import zipfile
from pathlib import Path

import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app import models
from app.items import baseline, readiness
from app.items.detection import validate_detection

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPORT_COMMAND = "python -m app.items.catalog_export export"
DEFAULT_DIR = REPO_ROOT / "catalog" / "items"
ZIP_PREFIX = "catalog/items/"
IMPORTED_BY = "catalog import"


# ---------- rendering ----------


class _Dumper(yaml.SafeDumper):
    """Deterministic, diff-friendly YAML: no aliases, multi-line text as
    literal blocks, no line folding."""

    def ignore_aliases(self, data):
        return True


def _str(dumper, value: str):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str)


def render(document: dict) -> str:
    return yaml.dump(document, Dumper=_Dumper, sort_keys=True, allow_unicode=True, default_flow_style=False, width=4096)


# ---------- export ----------


def _without(values: dict, *fields: str) -> dict:
    return {k: v for k, v in values.items() if k not in fields}


def _exported(row, *omit: str) -> dict:
    """A row's exported content: its baseline content, and for a
    soft-deleted row why it was deleted (`deleted_by`) — the reason is
    reviewable history, and a bootstrap must keep it. Not part of the seed
    baseline: a reseed never changes it."""
    values = _without(baseline.content(row), *omit)
    if row.deleted_at is not None:
        values["deleted_by"] = row.deleted_by
    return values


def documents(db: Session) -> list[tuple[models.CatalogItem, dict]]:
    """(item, document) for every item, soft-deleted included, in id order:
    the item's content, its resolutions' and their derivations'. Nested rows
    omit what nesting already says (item_id, resolution_id). Three queries
    for the whole catalog — the dashboard computes staleness on every poll."""
    derivations_by_resolution: dict[str, list[dict]] = {}
    for row in db.query(models.ResolutionDerivation).order_by(
            models.ResolutionDerivation.resolution_id, models.ResolutionDerivation.dependent_item_id):
        derivations_by_resolution.setdefault(row.resolution_id, []).append(
            {"dependent_item_id": row.dependent_item_id, **_exported(row, "item_id")})
    resolutions_by_item: dict[str, list[dict]] = {}
    for resolution in db.query(models.ItemResolution).order_by(models.ItemResolution.item_id, models.ItemResolution.id):
        resolutions_by_item.setdefault(resolution.item_id, []).append({
            "id": resolution.id, **_exported(resolution, "item_id"),
            "derivations": derivations_by_resolution.get(resolution.id, []),
        })
    return [(item, {"id": item.id, **_exported(item), "resolutions": resolutions_by_item.get(item.id, [])})
            for item in db.query(models.CatalogItem).order_by(models.CatalogItem.id)]


def export_files(db: Session) -> dict[str, str]:
    """{"<item-id>.yaml": text} for every item, soft-deleted included."""
    return {f"{item.id}.yaml": render(document) for item, document in documents(db)}


# ---------- staleness ----------


def _sha(text_: str) -> str:
    return hashlib.sha256(text_.encode("utf-8")).hexdigest()


def item_states(db: Session) -> dict[str, dict]:
    """{item_id: {"hash", "deleted", "name"}}: the hash is of the item's
    exported file, so it changes exactly when its file would."""
    return {item.id: {"hash": _sha(render(document)), "deleted": item.deleted_at is not None, "name": item.name}
            for item, document in documents(db)}


def catalog_hash(states: dict[str, dict]) -> str:
    return _sha("\n".join(f"{item_id} {state['hash']}" for item_id, state in sorted(states.items())))


def record_export(db: Session, out_dir: Path, states: dict[str, dict]) -> models.CatalogExport:
    row = models.CatalogExport(
        catalog_hash=catalog_hash(states), item_count=len(states), out_dir=str(out_dir),
        items={item_id: {"hash": state["hash"], "deleted": state["deleted"]} for item_id, state in sorted(states.items())},
    )
    db.add(row)
    db.flush()
    return row


def status(db: Session) -> dict:
    """How far the database has drifted from the last export into the
    repository. Read-only — never exports. Each changed item is `added` (not
    in the last export), `deleted` (soft-deleted since, or no longer in the
    database) or `edited` (its file would differ; a restore is an edit)."""
    last = db.query(models.CatalogExport).order_by(models.CatalogExport.id.desc()).first()
    current = item_states(db)
    exported = last.items if last is not None else {}
    changes = []
    for item_id, state in sorted(current.items()):
        before = exported.get(item_id)
        if before is None:
            change = "added"
        elif state["deleted"] and not before["deleted"]:
            change = "deleted"
        elif state["hash"] != before["hash"]:
            change = "edited"
        else:
            continue
        changes.append({"item_id": item_id, "item_name": state["name"], "change": change})
    for item_id in sorted(set(exported) - set(current)):
        changes.append({"item_id": item_id, "item_name": None, "change": "deleted"})
    changes.sort(key=lambda c: c["item_id"])
    return {
        "last_export": None if last is None else {
            "exported_at": last.exported_at, "catalog_hash": last.catalog_hash, "item_count": last.item_count,
        },
        "current_hash": catalog_hash(current),
        "is_current": last is not None and not changes,
        "changed": len(changes),
        "changes": changes,
        "command": EXPORT_COMMAND,
    }


def write(db: Session, out_dir: Path = DEFAULT_DIR) -> dict:
    """Writes the export into `out_dir`, which it owns: a .yaml file there
    for an item that no longer exists is removed. Bytes are written as-is
    (LF line endings), so an unchanged catalog leaves every file untouched.
    An export into the repository's catalog/items/ is recorded
    (catalog_exports), which is what staleness is measured against; an
    export anywhere else is not. Flushes; the caller commits."""
    files = export_files(db)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"written": [], "unchanged": 0, "removed": []}
    for name, content in files.items():
        path = out_dir / name
        data = content.encode("utf-8")
        if path.exists() and path.read_bytes() == data:
            report["unchanged"] += 1
            continue
        path.write_bytes(data)
        report["written"].append(name)
    for path in sorted(out_dir.glob("*.yaml")):
        if path.name not in files:
            path.unlink()
            report["removed"].append(path.name)
    report["recorded"] = False
    if out_dir.resolve() == DEFAULT_DIR.resolve():
        record_export(db, out_dir, {name[: -len(".yaml")]: {"hash": _sha(text_), "deleted": yaml.safe_load(text_)["deleted"]}
                                    for name, text_ in files.items()})
        report["recorded"] = True
    return report


def zip_bytes(files: dict[str, str]) -> bytes:
    """The export as a zip with fixed timestamps and order: the same catalog
    gives the same bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(ZIP_PREFIX + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name].encode("utf-8"))
    return buffer.getvalue()


# ---------- cached status ----------

# The status is a function of the catalog tables and catalog_exports only,
# and they change only when a person edits the catalog or runs the export.
# catalog_change_counter is bumped by a trigger on every statement that
# writes any of them, from any process (migration d3b8e5f07a29), inside the
# writer's transaction — so the new version becomes visible together with
# the rows it describes. A poll reads one number and recomputes only when it
# moved. Per server process; sync endpoints run on a thread pool, hence the
# lock.
_cache_lock = threading.Lock()
_cache: dict = {"version": None, "status": None, "computed": 0}


def catalog_version(db: Session) -> int:
    """The committed catalog change counter (or this session's own, if it has
    written catalog rows in its open transaction)."""
    return int(db.execute(text("SELECT version FROM catalog_change_counter WHERE id = 1")).scalar_one())


def cached_status(db: Session) -> dict:
    """`status`, recomputed only when a catalog row was written or an export
    ran since the last computation. The version is read before computing: a
    write committed during the computation moves the version, so the next
    poll recomputes; a stale status is never stored under a current version."""
    version = catalog_version(db)
    with _cache_lock:
        if _cache["version"] == version and _cache["status"] is not None:
            return _cache["status"]
    computed = status(db)
    with _cache_lock:
        _cache.update(version=version, status=computed, computed=_cache["computed"] + 1)
    return computed


def clear_cache() -> None:
    with _cache_lock:
        _cache.update(version=None, status=None)


# ---------- import ----------


def read_files(in_dir: Path = DEFAULT_DIR) -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(in_dir.glob("*.yaml"))}


def _deleted(values: dict, document: dict) -> dict:
    """A soft-deleted row keeps the reason it was deleted, as exported."""
    if not values.get("deleted"):
        return values
    return {**values, "_deleted_by": document.get("deleted_by") or IMPORTED_BY}


def import_files(db: Session, files: dict[str, str]) -> dict:
    """Imports exported documents through baseline.seed_row: never
    overwrites a row edited since it was seeded. Items first, then
    resolutions, then derivations (foreign keys). Detection is validated
    against the signal registry exactly as the API does. Flushes; the caller
    commits. Raises ValueError on a malformed export."""
    registered = {row.name: row.evidence_kind for row in db.query(models.SignalRegistryEntry)}
    if not registered:
        raise ValueError("signal_registry_entries is empty: seed the signal registry before importing the catalog")
    documents = []
    for name, content in sorted(files.items()):
        document = yaml.safe_load(content)
        if f"{document.get('id')}.yaml" != name:
            raise ValueError(f"{name}: holds item '{document.get('id')}'; the file name must be <item-id>.yaml")
        documents.append(document)

    report = baseline.new_report()
    report["mode"] = "bootstrap (empty catalog)" if db.query(models.CatalogItem).first() is None else "merge (seed_row)"
    item_fields = baseline.CONTENT_FIELDS[models.CatalogItem]
    for document in documents:
        values = {field: document[field] for field in item_fields}
        values["detection"], _warnings = validate_detection(values["scope"], values["detection"], registered)
        existing = db.get(models.CatalogItem, document["id"])
        before = (existing.detection, existing.scope) if existing is not None else None
        item, outcome = baseline.seed_row(db, models.CatalogItem, {"id": document["id"]}, _deleted(values, document), report)
        if outcome == "updated" and before != (item.detection, item.scope):
            item.version += 1
    db.flush()
    for document in documents:
        readiness.recompute_item(db, db.get(models.CatalogItem, document["id"]))

    resolution_fields = [f for f in baseline.CONTENT_FIELDS[models.ItemResolution] if f != "item_id"]
    for document in documents:
        for resolution in document.get("resolutions", []):
            values = {"item_id": document["id"], **{field: resolution[field] for field in resolution_fields}}
            baseline.seed_row(db, models.ItemResolution, {"id": resolution["id"]}, _deleted(values, resolution), report)
    db.flush()

    derivation_fields = [f for f in baseline.CONTENT_FIELDS[models.ResolutionDerivation] if f != "item_id"]
    for document in documents:
        for resolution in document.get("resolutions", []):
            for derivation in resolution.get("derivations", []):
                key = {"resolution_id": resolution["id"], "dependent_item_id": derivation["dependent_item_id"]}
                values = {"item_id": document["id"], **{field: derivation[field] for field in derivation_fields}}
                baseline.seed_row(db, models.ResolutionDerivation, key, _deleted(values, derivation), report)
    db.flush()
    return report


# ---------- round trip ----------


def roundtrip() -> bool:
    """Export the configured database, import into a fresh database (created,
    migrated, signal registry seeded, then dropped), export again, compare
    byte for byte. Returns whether the two exports are identical."""
    from app.config import settings
    from app.db import SessionLocal
    from app.items import registry
    from app.seed.seed_data import _load

    with SessionLocal() as db:
        first = export_files(db)

    source = make_url(settings.database_url)
    scratch_name = f"catalog_roundtrip_{uuid.uuid4().hex[:8]}"
    scratch_url = source.set(database=scratch_name)
    admin = create_engine(source.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{scratch_name}"'))
    print(f"Fresh database {scratch_name} created")
    engine = None
    try:
        env = {**os.environ, "DATABASE_URL": scratch_url.render_as_string(hide_password=False)}
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=Path(__file__).resolve().parents[2],
                       env=env, check=True, capture_output=True)
        print("  migrated to head")
        engine = create_engine(scratch_url)
        with Session(engine) as db:
            registry.sync_from_registry_files(db, _load("extractors.yaml")["extractors"], _load("anticipated_signals.yaml")["signals"])
            db.commit()
            print("  signal registry seeded (no catalog rows)")
            report = import_files(db, first)
            db.commit()
            print(f"  imported, {report['mode']}: {baseline.summary(report)}")
        with Session(engine) as db:
            second = export_files(db)
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{scratch_name}"'))
        admin.dispose()
        print(f"Fresh database {scratch_name} dropped")

    identical = first == second
    print(f"First export: {len(first)} files, {sum(len(t.encode()) for t in first.values())} bytes; "
          f"second export: {len(second)} files, {sum(len(t.encode()) for t in second.values())} bytes")
    print("Byte-identical: " + ("yes" if identical else "NO"))
    if not identical:
        for name in sorted(set(first) | set(second)):
            if first.get(name) != second.get(name):
                print(f"  differs: {name}")
    return identical


# ---------- CLI ----------


def main() -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description="Export the item catalog for review in git; import only to bootstrap.")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="Write catalog/items/<item-id>.yaml")
    export.add_argument("--out", type=Path, default=DEFAULT_DIR)
    imported = commands.add_parser("import", help="Import an export; never overwrites an edited row")
    imported.add_argument("--from", dest="source", type=Path, default=DEFAULT_DIR)
    imported.add_argument("--dry-run", action="store_true", help="Report what would change and write nothing.")
    commands.add_parser("roundtrip", help="Export, import into a fresh database, export, compare")
    args = parser.parse_args()

    if args.command == "roundtrip":
        sys.exit(0 if roundtrip() else 1)
    with SessionLocal() as db:
        if args.command == "export":
            report = write(db, args.out)
            db.commit()
            print(f"Exported to {args.out}: {len(report['written'])} written, {report['unchanged']} unchanged, "
                  f"{len(report['removed'])} removed" + ("; recorded as the current export" if report["recorded"] else
                                                       "; not recorded (not the repository's catalog/items)"))
            for name in report["written"] + report["removed"]:
                print(f"  {name}")
            return
        files = read_files(args.source)
        if not files:
            raise SystemExit(f"No <item-id>.yaml files in {args.source}")
        report = import_files(db, files)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
        print(("Would import" if args.dry_run else "Imported") + f", {report['mode']}: {baseline.summary(report)}")
        for key in ("inserted", "updated", "kept_edits"):
            for label in report[key]:
                print(f"  {key}: {label}")
        if report["conflicts"]:
            print(baseline.format_conflicts(report["conflicts"]))


if __name__ == "__main__":
    main()
