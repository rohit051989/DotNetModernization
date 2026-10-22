"""Reset client and repository data to a clean slate, keeping the catalog.

    python -m app.seed.reset_demo --yes          reset, then verify
    python -m app.seed.reset_demo --verify-only  verify only
    python -m app.seed.reset_demo --preflight-only  check it is safe to reset; change nothing

Refuses unless the deployment is explicitly a demo (DEPLOYMENT=demo in .env):
the default deployment is a client's, whose database is its only copy of its
data. Run through scripts/reset-demo.ps1. Clears every engagement and everything
scoped to one, every repository and everything derived from it, all
workflow history, the validation queue and backend/runs/; then creates the
demo engagements below. Keeps the catalog: catalog_items,
item_resolutions and resolution_derivations, the signal registry and extractors, step registrations and
job definitions, global step policies, catalog_revisions, and the legacy
patterns and target_state_options (master catalog, read by
pattern_migration.py --revert).

One transaction: either everything is cleared or nothing is. No CASCADE —
cascading from `engagements` would also empty the global step policies —
so every table is named, and the FK-referenced parents go last.
"""

import argparse
import shutil
import sys
from pathlib import Path

from sqlalchemy import text

from app import models
from app.config import settings
from app.db import SessionLocal

RUNS_DIR = settings.runs_path

# Truncated together in one statement, so FKs among them need no ordering.
# Nothing kept references any of these (checked against
# information_schema before this list was written).
CLEARED_TABLES = (
    # workflow history
    "validation_queue", "wf_artifacts", "wf_step_executions", "wf_job_executions", "wf_job_instances",
    # dependency-and-context-map output, and the annotations people keep on its register (client data)
    "integration_entry_points", "integration_edges", "origin_reconciliations", "dependency_cycles", "shared_libraries", "dependency_edges", "package_estate",
    "endpoint_register_services", "endpoint_register", "endpoint_annotations", "estate_sources",
    # solution-discovery to item-detection output
    "entry_point_backend", "entry_points", "entry_point_scans", "outbound_invocations", "outbound_scans", "package_assessments", "item_occurrences",
    "hierarchy_edges", "hierarchy_nodes",
    "fingerprint_signals", "project_fingerprints", "fingerprint_scans",
    "project_packages", "project_references", "solution_projects", "solutions",
    "repository_artifacts", "repository_structure", "projects",
    "repositories",
    # engagement-scoped
    "engagement_decisions", "engagement_item_scope", "engagement_patterns", "decision_records",
    # a client's WCF client matrix probe evidence and confirmations (29 C10)
    "engagement_matrix_confirmations", "engagement_probe_evidence",
)

KEPT_TABLES = (
    "catalog_items", "item_resolutions", "resolution_derivations", "signal_registry_entries", "extractors", "wf_step_registrations",
    "wf_job_definitions", "catalog_revisions", "patterns", "target_state_options",
    # What feeds said about packages: not client data, and reusing it is what
    # makes a rescan deterministic (30-DEPENDENCY-ASSESSMENT Part B6).
    "package_lookup_cache",
)

DEMO_ENGAGEMENTS = (
    {
        "id": "test-client-a",
        "client_name": "TestClientA",
        "description": "Demo engagement A. Windows and IIS estate to Linux on OpenShift 4.",
    },
    {
        "id": "test-client-b",
        "client_name": "TestClientB",
        "description": "Demo engagement B. Windows and IIS estate to Linux on OpenShift 4.",
    },
)
TARGET_PLATFORM = "Linux / OpenShift Container Platform 4"
DEFAULT_POSTURE = "lift-and-shift"

_IN_FLIGHT = ("STARTING", "STARTED", "STOPPING")


def preflight(db, force: bool) -> list[str]:
    """Refuses (returns problems) while a job is running or another session
    holds an open transaction — uvicorn mid-request, a BackgroundTasks job,
    a psql left in BEGIN. Idle pooled connections hold no locks and are
    only reported."""
    problems: list[str] = []
    running = db.execute(
        text("SELECT count(*) FROM wf_job_executions WHERE batch_status = ANY(:s)"), {"s": list(_IN_FLIGHT)}
    ).scalar()
    if running:
        problems.append(f"{running} job execution(s) are {'/'.join(_IN_FLIGHT)}: wait for them, or stop them, first")

    sessions = db.execute(
        text(
            """SELECT pid, coalesce(application_name, ''), state, xact_start IS NOT NULL
               FROM pg_stat_activity
               WHERE datname = current_database() AND pid <> pg_backend_pid() AND backend_type = 'client backend'"""
        )
    ).all()
    open_transactions = [s for s in sessions if s[3] and s[2] != "idle"]
    idle = [s for s in sessions if not s[3] or s[2] == "idle"]
    if open_transactions:
        detail = ", ".join(f"pid {pid} ({state})" for pid, _app, state, _x in open_transactions)
        message = f"{len(open_transactions)} other session(s) hold an open transaction: {detail}"
        if force:
            print(f"WARNING: {message}. Continuing because --force was given; the reset waits at most 10s for locks.")
        else:
            problems.append(message + ". Stop uvicorn (or finish the transaction), or pass --force")
    if idle:
        print(
            f"Note: {len(idle)} other idle connection(s) to this database (uvicorn's pool, most likely). "
            "They hold no transaction, so the reset can proceed; restart uvicorn afterwards to drop any cached state."
        )
    return problems


def reset(db) -> dict:
    before = {t: db.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in CLEARED_TABLES}
    before["engagements"] = db.execute(text("SELECT count(*) FROM engagements")).scalar()
    before["step_policies (engagement-scoped)"] = db.execute(
        text("SELECT count(*) FROM step_policies WHERE engagement_id IS NOT NULL")
    ).scalar()

    # Never wait indefinitely behind another session's lock.
    db.execute(text("SET LOCAL lock_timeout = '10s'"))
    db.execute(text(f"TRUNCATE {', '.join(CLEARED_TABLES)}"))
    db.execute(text("DELETE FROM step_policies WHERE engagement_id IS NOT NULL"))
    # Hard delete: client data, cleared on request. Nothing references an
    # engagement any more (validated by the FK constraints at commit).
    db.execute(text("DELETE FROM engagements"))

    for data in DEMO_ENGAGEMENTS:
        db.add(models.Engagement(target_platform=TARGET_PLATFORM, default_posture=DEFAULT_POSTURE, **data))
    db.flush()
    return before


def clear_runs_directory() -> int:
    """Deletes every run directory under backend/runs — nothing outside it."""
    if not RUNS_DIR.is_dir():
        return 0
    removed = 0
    for child in RUNS_DIR.iterdir():
        resolved = child.resolve()
        if resolved.parent != RUNS_DIR:
            raise RuntimeError(f"refusing to delete {resolved}: not directly under {RUNS_DIR}")
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    return removed


def verify(db) -> bool:
    """Prints the post-reset state; returns True when it is what a clean
    slate should be."""
    def count(sql: str) -> int:
        return db.execute(text(sql)).scalar()

    engagements = db.execute(
        text("SELECT id, client_name, target_platform, default_posture FROM engagements ORDER BY id")
    ).all()
    items = db.execute(text("SELECT state, count(*) FROM catalog_items WHERE deleted_at IS NULL GROUP BY state")).all()
    active_job = db.execute(
        text("SELECT version, validation_status FROM wf_job_definitions WHERE job_name = 'phase0-repository-discovery' AND is_active")
    ).all()
    runs_left = sum(1 for _ in RUNS_DIR.iterdir()) if RUNS_DIR.is_dir() else 0

    checks = [
        ("engagements", ", ".join(f"{e.client_name} ({e.id}; {e.target_platform}; {e.default_posture})" for e in engagements),
         [e.id for e in engagements] == [d["id"] for d in DEMO_ENGAGEMENTS]),
        ("repositories", count("SELECT count(*) FROM repositories"), count("SELECT count(*) FROM repositories") == 0),
        ("workflow executions", f"{count('SELECT count(*) FROM wf_job_executions')} job, "
                                f"{count('SELECT count(*) FROM wf_step_executions')} step, "
                                f"{count('SELECT count(*) FROM wf_artifacts')} artifacts",
         count("SELECT count(*) FROM wf_job_executions") + count("SELECT count(*) FROM wf_step_executions")
         + count("SELECT count(*) FROM wf_artifacts") + count("SELECT count(*) FROM wf_job_instances") == 0),
        ("validation queue", count("SELECT count(*) FROM validation_queue"), count("SELECT count(*) FROM validation_queue") == 0),
        ("decisions", f"{count('SELECT count(*) FROM engagement_decisions')} engagement_decisions, "
                      f"{count('SELECT count(*) FROM decision_records')} decision_records",
         count("SELECT count(*) FROM engagement_decisions") + count("SELECT count(*) FROM decision_records") == 0),
        ("engagement-scoped step policies", count("SELECT count(*) FROM step_policies WHERE engagement_id IS NOT NULL"),
         count("SELECT count(*) FROM step_policies WHERE engagement_id IS NOT NULL") == 0),
        ("global step policies (kept)", count("SELECT count(*) FROM step_policies WHERE engagement_id IS NULL"), True),
        ("catalog_items", ", ".join(f"{n} {state}" for state, n in items),
         dict(items) == {"ready": 27}),
        ("item_resolutions", count("SELECT count(*) FROM item_resolutions"), count("SELECT count(*) FROM item_resolutions") > 0),
        ("signal registry", f"{count('SELECT count(*) FROM signal_registry_entries')} signals, "
                            f"{count('SELECT count(*) FROM extractors')} extractors",
         count("SELECT count(*) FROM signal_registry_entries") > 0 and count("SELECT count(*) FROM extractors") > 0),
        ("legacy patterns (kept)", f"{count('SELECT count(*) FROM patterns')} patterns, "
                                   f"{count('SELECT count(*) FROM target_state_options')} target state options",
         count("SELECT count(*) FROM patterns") > 0),
        ("step registrations", count("SELECT count(*) FROM wf_step_registrations"), count("SELECT count(*) FROM wf_step_registrations") > 0),
        ("phase0-repository-discovery active", ", ".join(f"v{v} ({s})" for v, s in active_job) or "none",
         [v for v, _s in active_job] == [8]),
        ("backend/runs entries", runs_left, runs_left == 0),
    ]
    ok = True
    for label, value, passed in checks:
        ok &= passed
        print(f"  {'ok  ' if passed else 'FAIL'} {label:36} {value}")
    return ok


DEMO = "demo"


def demo_refusal(deployment: str) -> str | None:
    """Why this deployment may not be reset, or None for an explicitly marked demo.
    A client deployment's database is that client's only copy of its data."""
    if deployment == DEMO:
        return None
    return (f"this deployment is marked {deployment!r}, not 'demo'. The demo reset clears every engagement and "
            f"repository; on a client deployment that is the client's data. Only a deployment whose .env sets "
            f"DEPLOYMENT=demo can be reset.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset client and repository data, keeping the catalog")
    parser.add_argument("--yes", action="store_true", help="Required to reset: this deletes data")
    parser.add_argument("--force", action="store_true", help="Proceed even if another session holds an open transaction")
    parser.add_argument("--verify-only", action="store_true", help="Only print and check the current state")
    parser.add_argument("--preflight-only", action="store_true", help="Only check that a reset is safe now (exit 3 if not)")
    args = parser.parse_args()

    # Before anything else, every mode but --verify-only (which changes nothing).
    if not args.verify_only:
        refusal = demo_refusal(settings.deployment)
        if refusal:
            print(f"REFUSED: {refusal}")
            return 4

    db = SessionLocal()
    try:
        if args.preflight_only:
            problems = preflight(db, args.force)
            db.rollback()
            for problem in problems:
                print(f"REFUSED: {problem}")
            return 3 if problems else 0
        if not args.verify_only:
            if not args.yes:
                print("Refusing to reset without --yes.")
                return 2
            problems = preflight(db, args.force)
            db.rollback()
            if problems:
                for problem in problems:
                    print(f"REFUSED: {problem}")
                return 3
            before = reset(db)
            db.commit()
            print("Cleared (rows before reset):")
            for table, n in before.items():
                print(f"  {table:36} {n}")
            print(f"Removed {clear_runs_directory()} run director(ies) under {RUNS_DIR}")
            print(f"Created engagements: {', '.join(d['client_name'] for d in DEMO_ENGAGEMENTS)}")
        print("State:")
        return 0 if verify(db) else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
