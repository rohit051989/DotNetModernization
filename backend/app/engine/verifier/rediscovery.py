"""Re-discovery (36-COPILOT-ENHANCED-CONVERSION Part E), isolated: the platform's own per-repository discovery run
on a scratch worktree of a branch, in a scratch database, leaving no record in any engagement.

The client database is only read. A scratch database is created and bootstrapped as a new environment from the
repository (migrate, seed: platform configuration and the catalog from the committed export — the same bootstrap
as `python -m app.seed.reproduce`, which proves it equals this machine's catalog). Into it are copied the few rows
discovery reads for one engagement: the engagement itself, its item decisions and scope, its probe evidence and
matrix confirmations, and the package lookup cache: an experiment's frozen snapshot when it has one (Part L), and
then discovery runs with `lookup_offline`, so no lookup reaches a live feed; otherwise the shared cache, so dependency
assessment answers as it does here. A
worker process pointed at the scratch database (DATABASE_URL) and a scratch runs folder (RUNS_DIR) registers the
worktree, runs phase0-repository-discovery through impact-analysis, and writes what it found to a file. The
database is then dropped and the runs folder deleted: nothing is left behind, soft-deleted or otherwise.

    python -m app.engine.verifier.rediscovery --worker --engagement E --path <worktree> --name N --out snap.json
    (the worker, run by `snapshot`; it refuses to run against anything but a verifier scratch database)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app import models
from app.config import settings

JOB = "phase0-repository-discovery"
BACKEND = Path(__file__).resolve().parents[3]

# What one engagement's discovery reads beyond the repository itself: (table, column scoping it to the
# engagement, or None for shared rows). Copied in this order, so foreign keys hold.
ENGAGEMENT_ROWS = (
    ("engagements", "id"),
    ("engagement_item_scope", "engagement_id"),
    ("engagement_decisions", "engagement_id"),
    ("engagement_probe_evidence", "engagement_id"),
    ("engagement_matrix_confirmations", "engagement_id"),
    ("package_lookup_cache", None),
)


class RediscoveryFailed(RuntimeError):
    pass


def _copy(source_url: str, target_url: str, engagement_id: str, lookups: list[dict] | None = None) -> dict[str, int]:
    """Copies the engagement's rows. With `lookups` (a frozen snapshot), the package lookup cache is the snapshot's
    rows and nothing of the live cache."""
    source, target = create_engine(source_url), create_engine(target_url)
    counts = {}
    try:
        with source.connect() as read, target.begin() as write:
            for name, column in ENGAGEMENT_ROWS:
                if name == "package_lookup_cache" and lookups is not None:
                    rows = [{"feed_url_normalised": r["feed"], "package_id": r["package"], "versions": r["versions"],
                             "metadata": r["metadata"], "fetched_at": r["fetchedAt"]} for r in lookups]
                    if rows:
                        write.execute(Table(name, MetaData(), autoload_with=target).insert(), rows)
                    counts[f"{name} (frozen snapshot)"] = len(rows)
                    continue
                table = Table(name, MetaData(), autoload_with=source)
                query = select(table) if column is None else select(table).where(table.c[column] == engagement_id)
                rows = [dict(r) for r in read.execute(query).mappings()]
                if name == "engagement_decisions":     # a decision can derive from another: parents first
                    rows.sort(key=lambda r: r.get("derived_from_decision_id") is not None)
                if rows:
                    write.execute(Table(name, MetaData(), autoload_with=target).insert(), rows)
                counts[name] = len(rows)
    finally:
        source.dispose()
        target.dispose()
    return counts


def snapshot(engagement_id: str, worktree: Path, name: str, scratch_dir: Path, lookups: list[dict] | None = None) -> dict:
    """Discovery of `worktree` as `engagement_id` sees it, run in a scratch database that is dropped afterwards. With
    `lookups`, package lookups are answered from that frozen snapshot only, offline."""
    from app.seed.reproduce import Scratch

    scratch_dir.mkdir(parents=True, exist_ok=True)
    runs = scratch_dir / "runs"
    out = scratch_dir / f"snapshot-{uuid.uuid4().hex[:8]}.json"
    try:
        with Scratch(make_url(settings.database_url), "verifier") as scratch:
            scratch.bootstrap()
            url = scratch.url.render_as_string(hide_password=False)
            copied = _copy(settings.database_url, url, engagement_id, lookups)
            env = {**os.environ, "DATABASE_URL": url, "RUNS_DIR": str(runs)}
            done = subprocess.run([sys.executable, "-m", "app.engine.verifier.rediscovery", "--worker",
                                   "--engagement", engagement_id, "--path", str(worktree), "--name", name, "--out", str(out)]
                                  + (["--offline"] if lookups is not None else []),
                                  cwd=BACKEND, env=env, capture_output=True, text=True, timeout=7200)
            if done.returncode != 0 or not out.exists():
                raise RediscoveryFailed(f"isolated discovery of {worktree} failed:\n{done.stdout[-3000:]}\n{done.stderr[-3000:]}")
            snap = json.loads(out.read_text(encoding="utf-8"))
            snap["isolation"] = {"scratch_database": scratch.name, "copied": copied, "dropped": True}
            return snap
    finally:
        out.unlink(missing_ok=True)
        if runs.exists():
            shutil.rmtree(runs, ignore_errors=True)


def _worker(engagement_id: str, worktree: Path, name: str, out: Path, offline: bool = False) -> int:
    """Runs inside the scratch database only. Refuses to run against any other database."""
    from app.conversion import planner
    from app.db import SessionLocal
    from app.engine.inputs.collect import collect
    from app.repositories import service as repositories
    from app.repositories.schemas import RegisterLocalPathRequest
    from app.workflow.runtime import service as runtime

    if not (make_url(settings.database_url).database or "").startswith("verifier_"):
        print("refused: the re-discovery worker runs only in a verifier scratch database", file=sys.stderr)
        return 2
    db: Session = SessionLocal()
    try:
        engagement = db.get(models.Engagement, engagement_id)
        repository = repositories.register_local_path(db, engagement, RegisterLocalPathRequest(
            source_type="local_path", local_path=str(worktree), name=name))
        db.commit()
        parameters = {"engagement_id": engagement_id, "repository_id": str(repository.id),
                      "ingest_token": repository.ingest_token or str(uuid.uuid4())}
        if offline:
            parameters["lookup_offline"] = True      # dependency-assessment: the frozen snapshot only, no feed
        execution = runtime.launch_job(db, JOB, parameters, triggered_by="manual")
        db.commit()
        steps = {s.step_name: s.exit_status for s in runtime.get_step_executions(db, execution.id)}
        if execution.batch_status != "COMPLETED":
            print(f"discovery ended {execution.batch_status}/{execution.exit_status}: {steps}", file=sys.stderr)
            return 1
        db.refresh(repository)
        model = collect(db, repository)
        try:
            unit_tests = planner._unit_test_projects(db, repository.id)
            solution = planner._solution(db, repository.id, unit_tests)
        except (LookupError, ValueError) as err:
            unit_tests, solution = [], None
            model["test_projects_problem"] = str(err)
        out.write_text(json.dumps({"steps": steps, "model": model, "unit_test_projects": unit_tests, "solution": solution},
                                  indent=2, sort_keys=True, default=str), encoding="utf-8")
        return 0
    finally:
        db.close()


def work_items(model: dict) -> dict[tuple[str, str], dict]:
    """{(project, item): {occurrences: n, places: [file:line ...]}} — a work item is a found (project, item)."""
    out: dict[tuple[str, str], dict] = {}
    for item in model["items"]:
        for occ in item["occurrences"]:
            entry = out.setdefault((occ["project"], item["id"]), {"occurrences": 0, "places": []})
            entry["occurrences"] += 1
            for line in occ["lines"] or [None]:
                place = (occ["file"] or occ["project"]) + (f":{line['line']}" if line else "")
                if place not in entry["places"]:
                    entry["places"].append(place)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true", required=True)
    parser.add_argument("--engagement", required=True)
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--offline", action="store_true", help="answer package lookups from the scratch cache only")
    a = parser.parse_args()
    sys.exit(_worker(a.engagement, a.path, a.name, a.out, a.offline))
