"""Register repositories and run discovery from the command line — the same service calls the API makes
(app/routers/repositories.py), run synchronously in this process, so the backend does not need to be running.

    python -m app.repositories.cli register --engagement test-client-a --path D:\\...\\AccountsApi.Net10 --clone-url https://...
    python -m app.repositories.cli discover --engagement test-client-a --repository accountsapi-net10
    python -m app.repositories.cli consolidate --engagement test-client-a

`register` registers the folder and runs phase0-repository-discovery on it, as registering through the API does.
`discover` is a rescan: a new ingest token, so a new job instance. `consolidate` runs phase0-estate-consolidation
over the engagement's repositories.
"""
import argparse
import sys
import uuid

from app import models
from app.repositories import service
from app.repositories.schemas import RegisterLocalPathRequest
from app.workflow.runtime import service as runtime

DISCOVERY = "phase0-repository-discovery"
CONSOLIDATION = "phase0-estate-consolidation"


def _report(db, execution: models.WfJobExecution) -> int:
    steps = runtime.get_step_executions(db, execution.id)
    for s in steps:
        print(f"  {s.step_name:40} {s.batch_status:10} {s.exit_status or ''}")
    print(f"{execution.batch_status} / {execution.exit_status}")
    return 0 if execution.batch_status == "COMPLETED" else 1


def discover(db, repository: models.Repository, lookup_offline: bool = False) -> models.WfJobExecution:
    """`lookup_offline`: dependency-assessment answers package lookups from the lookup cache only, contacting no feed
    (36-COPILOT-ENHANCED-CONVERSION Part L): rediscovering an experiment's repository against the answers its frozen
    snapshot holds, so no release published since changes them."""
    token = service.start_rescan(repository)
    db.commit()
    parameters = {"engagement_id": repository.engagement_id, "repository_id": str(repository.id), "ingest_token": token}
    if lookup_offline:
        parameters["lookup_offline"] = True
    execution = runtime.launch_job(db, DISCOVERY, parameters, triggered_by="manual")
    db.commit()
    return execution


def main(argv: list[str] | None = None) -> int:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(prog="python -m app.repositories.cli", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("register")
    r.add_argument("--engagement", required=True)
    r.add_argument("--path", required=True)
    r.add_argument("--clone-url")
    r.add_argument("--name")
    d = sub.add_parser("discover")
    d.add_argument("--engagement", required=True)
    d.add_argument("--repository", required=True, help="repository slug")
    d.add_argument("--lookup-offline", action="store_true",
                   help="answer package lookups from the lookup cache only; no feed is contacted")
    c = sub.add_parser("consolidate")
    c.add_argument("--engagement", required=True)
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        engagement = db.get(models.Engagement, args.engagement)
        if engagement is None or engagement.deleted_at is not None:
            print(f"no engagement {args.engagement}", file=sys.stderr)
            return 1
        if args.command == "register":
            try:
                repository = service.register_local_path(db, engagement, RegisterLocalPathRequest(
                    source_type="local_path", local_path=args.path, clone_url=args.clone_url, name=args.name))
            except service.RegistrationError as err:
                print(f"refused: {err}", file=sys.stderr)
                return 1
            db.commit()
            print(f"registered {repository.slug} ({repository.id})")
            return _report(db, discover(db, repository))
        if args.command == "discover":
            repository = (db.query(models.Repository).filter_by(engagement_id=engagement.id, slug=args.repository)
                          .filter(models.Repository.deleted_at.is_(None)).one())
            return _report(db, discover(db, repository, args.lookup_offline))
        execution = runtime.launch_job(db, CONSOLIDATION, {"engagement_id": engagement.id, "run_token": str(uuid.uuid4())},
                                       triggered_by="manual")
        db.commit()
        return _report(db, execution)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
