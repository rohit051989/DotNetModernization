"""python -m app.results copy-existing: copies the results of scans made before central results into the database.

Run once, on the machine that made the scans (a repository's owner's), as the user registered for that machine and
Windows account, like every command-line tool (app.auth.service.cli_actor): it reads this machine's RUNS_DIR. For each
repository (and each engagement's estate), the newest RESULTS_KEEP of each kind of result whose file is here are
copied; what is already in the database is left as it is. Run folders are not changed. A repository whose owner
never runs it shows its results after its next scan.

    python -m app.results copy-existing                  every repository whose scans are on this machine
    python -m app.results copy-existing --repository eshop
    python -m app.results copy-existing --dry-run        what would be copied
"""
import argparse
import sys
import uuid

from sqlalchemy import text

from app import models
from app.auth import service as auth
from app.config import settings
from app.db import SessionLocal
from app.results import store
from app.workflow.adapters.base import local_path_from_uri


def _candidates(db, repository: models.Repository | None):
    """(scope, artifact type) -> the wf_artifacts of that kind, newest first, with their scope from the job."""
    rows = db.execute(text("""
        select w.id, w.artifact_type, w.created_at,
               i.parameters->>'repository_id' as repository_id, i.parameters->>'engagement_id' as engagement_id
        from wf_artifacts w
        join wf_job_executions j on j.id = w.job_execution_id
        join wf_job_instances i on i.id = j.job_instance_id
        where w.artifact_type = any(:types)
        order by w.created_at desc, w.id desc
    """), {"types": list(store.RESULT_TYPES)}).all()
    groups: dict[tuple, list] = {}
    for row in rows:
        if row.artifact_type in store.REPOSITORY_TYPES:
            if not row.repository_id or (repository is not None and row.repository_id != str(repository.id)):
                continue
            key = ("repository", row.repository_id, row.artifact_type)
        else:
            if not row.engagement_id or (repository is not None and row.engagement_id != repository.engagement_id):
                continue
            key = ("engagement", row.engagement_id, row.artifact_type)
        groups.setdefault(key, []).append(row.id)
    return groups


def copy_existing(db, repository: models.Repository | None = None, dry_run: bool = False, out=print) -> dict:
    """Copies the newest RESULTS_KEEP of each kind whose file is on this machine. Returns the counts."""
    counts = {"copied": 0, "already": 0, "not_here": 0, "pruned": 0}
    repositories = {str(r.id): r.slug for r in db.query(models.Repository)}
    for (kind, scope_id, artifact_type), ids in sorted(_candidates(db, repository).items()):
        copied = 0
        for artifact_id in ids[:settings.results_keep]:
            artifact = db.get(models.WfArtifact, artifact_id)
            if store.is_stored(db, artifact.id):
                counts["already"] += 1
                continue
            try:
                here = local_path_from_uri(artifact.uri).is_file()
            except ValueError:
                here = False
            if not here:
                counts["not_here"] += 1
                continue
            if not dry_run and store.publish(db, artifact, prune_after=False):
                copied += 1
            elif dry_run:
                copied += 1
        if copied:
            name = repositories.get(scope_id, scope_id) if kind == "repository" else f"estate of {scope_id}"
            out(f"{'would copy' if dry_run else 'copied'} {copied} {artifact_type} of {name}")
        counts["copied"] += copied
        if not dry_run:
            counts["pruned"] += store.prune(db, artifact_type,
                                            repository_id=uuid.UUID(scope_id) if kind == "repository" else None,
                                            engagement_id=scope_id if kind == "engagement" else None)
    if not dry_run:
        db.commit()
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.results", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    copy = sub.add_parser("copy-existing", help="copy the results of earlier scans on this machine into the database")
    copy.add_argument("--repository", help="one repository, by slug or id (with its engagement's estate)")
    copy.add_argument("--dry-run", action="store_true", help="say what would be copied, change nothing")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        auth.cli_actor(db)
        repository = None
        if args.repository:
            repository = next((r for r in db.query(models.Repository).filter(models.Repository.deleted_at.is_(None))
                               if args.repository in (r.slug, str(r.id))), None)
            if repository is None:
                print(f"No repository '{args.repository}'.", file=sys.stderr)
                return 1
        counts = copy_existing(db, repository, dry_run=args.dry_run)
        verb = "Would copy" if args.dry_run else "Copied"
        print(f"{verb} {counts['copied']} result(s); {counts['already']} already in the database; "
              f"{counts['not_here']} not on this machine (scanned elsewhere, or their run folder was removed)"
              + ("" if args.dry_run else f"; {counts['pruned']} older one(s) pruned (RESULTS_KEEP={settings.results_keep})."))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
