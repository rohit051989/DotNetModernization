"""Does the platform reproduce from the repository alone?

Bootstraps a scratch schema exactly as a new environment is stood up
(28-ITEM Part W, "Standing up a new environment"): migrate to head, then
`python -m app.seed` — platform configuration (steps, jobs, signal registry,
extractors) from the seed's files, and the item catalog from the committed
export in catalog/items/ (the factory YAML only when no export exists). Then
compares it with the platform's own schema (DB_SCHEMA in DB_NAME) and drops it. The scratch schema is in the
same database: creating it needs CREATE on the database, never the right to create a database.

    python -m app.seed.reproduce                            # the check
    python -m app.seed.reproduce --verbose                  # also the seed output, row counts and history
    python -m app.seed.reproduce --prove-export-bootstrap   # proof: a catalog edit survives export -> bootstrap

Compared — platform configuration and catalog: step registrations (adapter
and contract included), job definitions and which version is active, global
step policies, the signal registry, extractors, the legacy pattern catalog,
and the item catalog (items, resolutions, derivations).

Not compared — client data and run history (engagements, decisions,
repositories, scans and their outputs, executions, validation queue,
engagement-scoped policies, catalog exports), and computed or bookkeeping
columns: timestamps (a soft delete is compared as deleted or not), seed
baselines (`seeded_hash`), and the catalog's `version` counters, which count
the edits made on one machine.

Historical records are intentionally not reproduced and are not differences:
retired step registrations, superseded job definition versions, and
soft-deleted catalog rows a bootstrap never creates. A clean run reports one
line counting them and zero differences. Any difference is something that
exists only on this machine (or only in the repository); the command exits 1.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import settings
from app.db import make_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]

# table -> (key columns, WHERE, extra excluded columns)
TABLES: dict[str, tuple[tuple[str, ...], str | None, tuple[str, ...]]] = {
    "wf_step_registrations": (("step_name",), None, ()),
    "wf_job_definitions": (("job_name", "version"), None, ("id",)),
    "step_policies": (("step_name",), "engagement_id IS NULL", ("id", "set_by")),
    "signal_registry_entries": (("name",), None, ()),
    "extractors": (("name",), None, ()),
    "patterns": (("id",), None, ("version",)),
    "target_state_options": (("id",), None, ("version",)),
    "catalog_items": (("id",), None, ("seeded_hash", "version")),
    "item_resolutions": (("id",), None, ("seeded_hash",)),
    "resolution_derivations": (("resolution_id", "dependent_item_id"), None, ("seeded_hash",)),
    "conversion_recipes": (("id",), None, ()),
    "conversion_recipe_steps": (("recipe_id", "step_id"), None, ()),
}


# ---------- scratch schemas ----------


class Scratch:
    """A throwaway schema in the platform's own database, created for one run and always dropped (01-ENVIRONMENT-SETUP
    section 10). The same at the client as here: creating a schema needs CREATE on the database, never the right to
    create databases. Its name starts with `label`, so a worker can tell a scratch schema from the platform's own."""

    def __init__(self, label: str):
        from app.config import database_url

        self.name = f"{label}_{uuid.uuid4().hex[:8]}"
        self.url = database_url(self.name)
        self._admin = make_engine(settings.database_url, isolation_level="AUTOCOMMIT")
        self.engine: Engine | None = None

    def __enter__(self) -> "Scratch":
        with self._admin.connect() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.name}"'))
        return self

    def __exit__(self, *exc) -> None:
        if self.engine is not None:
            self.engine.dispose()
        with self._admin.connect() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{self.name}" CASCADE'))
        self._admin.dispose()

    def bootstrap(self, extra_env: dict | None = None) -> str:
        """Stands the schema up as a new environment; returns the seed's output."""
        env = {**os.environ, "DB_SCHEMA": self.name, **(extra_env or {})}
        output = []
        for command in (["-m", "alembic", "upgrade", "head"], ["-m", "app.seed"]):
            result = subprocess.run([sys.executable, *command], cwd=BACKEND_DIR, env=env, capture_output=True, text=True)
            if result.returncode != 0:
                raise SystemExit(f"Bootstrapping {self.name} failed at {' '.join(command[1:])}:\n"
                                 f"{result.stdout[-3000:]}\n{result.stderr[-3000:]}")
            output.append(result.stdout)
        self.engine = make_engine(self.url)
        return "".join(output)


# ---------- comparison ----------


def _rows(engine: Engine, table: str) -> dict[tuple, dict]:
    keys, where, excluded = TABLES[table]
    columns = [c["name"] for c in inspect(engine).get_columns(table)]
    sql = f"SELECT * FROM {table}" + (f" WHERE {where}" if where else "")
    result = {}
    with engine.connect() as connection:
        for mapping in connection.execute(text(sql)).mappings():
            row = {}
            for column in columns:
                if column in excluded:
                    continue
                if column == "deleted_at":
                    row["deleted"] = mapping[column] is not None
                elif column.endswith("_at"):
                    continue
                else:
                    row[column] = mapping[column]
            result[tuple(row[k] for k in keys)] = row
    return result


def _history(table: str, row: dict, live_rows: dict[tuple, dict]) -> str | None:
    """Why a row only on this machine is history rather than a difference."""
    if table == "wf_step_registrations" and (row.get("deleted") or row.get("implementation_status") == "deprecated"):
        return "retired step registration"
    if table == "wf_job_definitions" and not row["is_active"]:
        active = [r["version"] for r in live_rows.values() if r["job_name"] == row["job_name"] and r["is_active"]]
        if active and row["version"] < active[0]:
            return "superseded job definition version"
    if table in ("catalog_items", "item_resolutions", "resolution_derivations", "patterns", "target_state_options") and row.get("deleted"):
        return "soft-deleted catalog row"
    return None


def _short(value) -> str:
    rendered = json.dumps(value, default=str, ensure_ascii=False, sort_keys=True)
    return rendered if len(rendered) <= 160 else rendered[:157] + "..."


def compare(live: Engine, fresh: Engine) -> dict:
    report = {"differences": [], "history": [], "compared": {}}
    for table in TABLES:
        live_rows, fresh_rows = _rows(live, table), _rows(fresh, table)
        report["compared"][table] = (len(live_rows), len(fresh_rows))
        for key in sorted(set(live_rows) | set(fresh_rows), key=lambda k: tuple(str(p) for p in k)):
            label = f"{table} {'/'.join(str(p) for p in key)}"
            if key not in fresh_rows:
                why = _history(table, live_rows[key], live_rows)
                if why:
                    report["history"].append(f"{label} ({why})")
                else:
                    report["differences"].append({"row": label, "what": "only on this machine — the repository does not reproduce it"})
            elif key not in live_rows:
                report["differences"].append({"row": label, "what": "only in the repository — this machine does not have it"})
            else:
                fields = {f: (live_rows[key][f], fresh_rows[key].get(f)) for f in live_rows[key]
                          if live_rows[key][f] != fresh_rows[key].get(f)}
                if fields:
                    report["differences"].append({"row": label, "what": "differs", "fields": fields})
    return report


def print_differences(differences: list[dict]) -> None:
    for difference in differences:
        print(f"  {difference['row']}: {difference['what']}")
        for field, (here, repository) in difference.get("fields", {}).items():
            print(f"      {field}: this machine {_short(here)} | repository {_short(repository)}")


# ---------- the check ----------


def check(verbose: bool) -> int:
    from app.config import settings
    from app.seed import catalog_source

    catalog_from = (f"the export in {catalog_source.export_dir()}" if catalog_source.export_exists()
                    else "the factory defaults (no export in the repository)")
    live = make_engine(settings.database_url)
    try:
        with Scratch("platform_reproduce") as fresh:
            output = fresh.bootstrap()
            report = compare(live, fresh.engine)
    finally:
        live.dispose()

    print(f"Bootstrapped a fresh schema from the repository: platform configuration from the seed, catalog from {catalog_from}.")
    if verbose:
        for line in output.splitlines():
            print(f"    {line}")
        print("Compared (this machine / repository):")
        for table, (here, repository) in report["compared"].items():
            print(f"  {table:<26} {here:>4} / {repository:<4}")
    print(f"{len(report['history'])} historical records intentionally not reproduced"
          + (" (--verbose lists them)" if report["history"] and not verbose else ""))
    if verbose:
        for line in report["history"]:
            print(f"  {line}")
    differences = report["differences"]
    print(f"{len(differences)} difference{'' if len(differences) == 1 else 's'}")
    if differences:
        print_differences(differences)
        return 1
    return 0


# ---------- the proof ----------

PROOF_ITEM = "datetime-now-usage"
PROOF_DESCRIPTION = "Edited in a scratch environment by the export-bootstrap proof (python -m app.seed.reproduce)."


def prove_export_bootstrap() -> int:
    """A catalog edit made in the UI reaches a new environment through the
    export: bootstrap A, edit one item in A through the API handler the UI
    calls, export A, bootstrap B from that export alone, and compare."""
    from app.config import settings
    from app.items import catalog_export
    from app.items import schemas as item_schemas
    from app.routers import catalog_items
    from app.seed.seed_data import authored_item

    factory = authored_item(PROOF_ITEM)["description"]
    export_dir = Path(tempfile.mkdtemp(prefix="catalog-export-proof-"))
    try:
        with Scratch("bootstrap_proof_a") as a:
            a.bootstrap()
            with Session(a.engine) as db:
                item = db.get(catalog_items.models.CatalogItem, PROOF_ITEM)
                catalog_items.update_item(PROOF_ITEM, item_schemas.CatalogItemWrite(
                    name=item.name, description=PROOF_DESCRIPTION, scope=item.scope, category=item.category,
                    detection=item.detection, excluded_roles=item.excluded_roles, owner_team=item.owner_team,
                    status=item.status), db=db, if_match=str(item.edit_version))
                catalog_export.write(db, export_dir)
                db.commit()
                exported_a = catalog_export.export_files(db)
            print(f"A: bootstrapped, '{PROOF_ITEM}' edited in the UI path, exported ({len(exported_a)} files)")

            with Scratch("bootstrap_proof_b") as b:
                b.bootstrap({"CATALOG_EXPORT_DIR": str(export_dir)})
                with Session(b.engine) as db:
                    exported_b = catalog_export.export_files(db)
                    description_b = db.get(catalog_items.models.CatalogItem, PROOF_ITEM).description
                catalog_report = compare(a.engine, b.engine)
            print("B: bootstrapped from A's export alone")
    finally:
        shutil.rmtree(export_dir, ignore_errors=True)

    checks = {
        f"B carries the edit to '{PROOF_ITEM}', not the factory description": description_b == PROOF_DESCRIPTION != factory,
        "B's catalog exports byte-identically to A's": exported_a == exported_b,
        "B reproduces A with zero differences": not catalog_report["differences"],
    }
    for label, passed in checks.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {label}")
    if catalog_report["differences"]:
        print_differences(catalog_report["differences"])
    return 0 if all(checks.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove the platform reproduces from the repository alone.")
    parser.add_argument("--verbose", action="store_true", help="Also print the seed output, row counts and historical records.")
    parser.add_argument("--prove-export-bootstrap", action="store_true",
                        help="Prove a catalog edit reaches a new environment through the export.")
    args = parser.parse_args()
    if args.prove_export_bootstrap:
        return prove_export_bootstrap()
    return check(args.verbose)


if __name__ == "__main__":
    sys.exit(main())
