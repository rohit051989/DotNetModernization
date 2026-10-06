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
`deleted: true` — a deletion is a reviewable change. Engagement data
(decisions, scope) is client data, not catalog content, and never exported.

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
import io
import os
import subprocess
import sys
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


def item_document(db: Session, item: models.CatalogItem) -> dict:
    """The item's content, its resolutions' and their derivations'. Nested
    rows omit what nesting already says (item_id, resolution_id)."""
    resolutions = []
    for resolution in db.query(models.ItemResolution).filter(models.ItemResolution.item_id == item.id).order_by(models.ItemResolution.id):
        derivations = [
            {"dependent_item_id": row.dependent_item_id, **_without(baseline.content(row), "item_id")}
            for row in db.query(models.ResolutionDerivation)
            .filter(models.ResolutionDerivation.resolution_id == resolution.id)
            .order_by(models.ResolutionDerivation.dependent_item_id)
        ]
        resolutions.append({"id": resolution.id, **_without(baseline.content(resolution), "item_id"), "derivations": derivations})
    return {"id": item.id, **baseline.content(item), "resolutions": resolutions}


def export_files(db: Session) -> dict[str, str]:
    """{"<item-id>.yaml": text} for every item, soft-deleted included."""
    return {f"{item.id}.yaml": render(item_document(db, item))
            for item in db.query(models.CatalogItem).order_by(models.CatalogItem.id)}


def write(db: Session, out_dir: Path = DEFAULT_DIR) -> dict:
    """Writes the export into `out_dir`, which it owns: a .yaml file there
    for an item that no longer exists is removed. Bytes are written as-is
    (LF line endings), so an unchanged catalog leaves every file untouched."""
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


# ---------- import ----------


def read_files(in_dir: Path = DEFAULT_DIR) -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(in_dir.glob("*.yaml"))}


def _deleted(values: dict) -> dict:
    return {**values, "_deleted_by": IMPORTED_BY} if values.get("deleted") else values


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
        item, outcome = baseline.seed_row(db, models.CatalogItem, {"id": document["id"]}, _deleted(values), report)
        if outcome == "updated" and before != (item.detection, item.scope):
            item.version += 1
    db.flush()
    for document in documents:
        readiness.recompute_item(db, db.get(models.CatalogItem, document["id"]))

    resolution_fields = [f for f in baseline.CONTENT_FIELDS[models.ItemResolution] if f != "item_id"]
    for document in documents:
        for resolution in document.get("resolutions", []):
            values = {"item_id": document["id"], **{field: resolution[field] for field in resolution_fields}}
            baseline.seed_row(db, models.ItemResolution, {"id": resolution["id"]}, _deleted(values), report)
    db.flush()

    derivation_fields = [f for f in baseline.CONTENT_FIELDS[models.ResolutionDerivation] if f != "item_id"]
    for document in documents:
        for resolution in document.get("resolutions", []):
            for derivation in resolution.get("derivations", []):
                key = {"resolution_id": resolution["id"], "dependent_item_id": derivation["dependent_item_id"]}
                values = {"item_id": document["id"], **{field: derivation[field] for field in derivation_fields}}
                baseline.seed_row(db, models.ResolutionDerivation, key, _deleted(values), report)
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
            print(f"Exported to {args.out}: {len(report['written'])} written, {report['unchanged']} unchanged, "
                  f"{len(report['removed'])} removed")
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
