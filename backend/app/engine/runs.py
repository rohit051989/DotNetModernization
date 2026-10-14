"""Engine run records (36-COPILOT-ENHANCED-CONVERSION Parts D, F and I).

A conversion engine run is executed by a person in their own tool, signed in with their own
company-managed account. The platform records it; it never launches the engine and never sees the
engine's credential.

    python -m app.engine.runs start --engagement test-client-a --repository eshoponweb --label arm2-run1
        --worktree <path> --base 4da8212 --provider github-copilot --organisation <org>
        --identity <signed-in account> --model "<model>" --engine-version "<version>" [--host "..."]
        [--runbook <file>]
    python -m app.engine.runs intervene --engagement test-client-a --label arm2-run1 --stage execution --what "..."
    python -m app.engine.runs finish --engagement test-client-a --label arm2-run1 --outcome completed
        --elapsed-minutes 95 --premium-requests 41 [--transcript <file>] [--notes "..."]
    python -m app.engine.runs show --engagement test-client-a [--label arm2-run1]

`start` is the boundary. It refuses unless the engagement's allowlist admits the provider under the
organisation the engine reports (app.engine.boundary), and refuses any value shaped like a
credential. It records a sha256 for every input file present in the worktree — everything under the
generated input paths (app.engine.paths), plus the runbook the person follows — so a result can
always be traced to exactly what the engine was given. An arm without generated inputs records the
runbook alone.
"""
import argparse
import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from app import models
from app.engine import boundary, paths


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def input_hashes(worktree: Path, runbook: Path | None = None) -> list[dict]:
    """[{path, sha256}] for every file under the generated input paths, sorted by path; the
    runbook, when given, as `runbook:<file name>`."""
    found = []
    for prefix in paths.GENERATED_INPUT_PATHS:
        target = worktree / prefix.rstrip("/")
        files = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file()) if target.is_dir() else []
        for f in files:
            found.append({"path": f.relative_to(worktree).as_posix(), "sha256": _sha256(f)})
    found.sort(key=lambda e: e["path"])
    if runbook is not None:
        found.append({"path": f"runbook:{runbook.name}", "sha256": _sha256(runbook)})
    return found


def _git(worktree: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, text=True, check=True).stdout.strip()


def start(db: Session, *, engagement_id: str, label: str, provider: str, organisation: str, identity: str,
          model: str, engine_version: str, host: str | None = None, repository_slug: str | None = None,
          worktree: Path | None = None, base_commit: str | None = None, runbook: Path | None = None) -> models.EngineRun:
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None or engagement.deleted_at is not None:
        raise LookupError(f"no engagement {engagement_id}")
    for field, value in (("identity", identity), ("organisation", organisation), ("model", model),
                         ("engine version", engine_version), ("host", host), ("label", label)):
        boundary.refuse_credential(field, value)
    for field, value in (("identity", identity), ("organisation", organisation), ("model", model),
                         ("engine version", engine_version)):
        if not value or not value.strip():
            raise ValueError(f"{field} is required: record it as the engine reports it")
    boundary.require_allowed(engagement, provider, organisation)

    repository = None
    if repository_slug:
        repository = (db.query(models.Repository).filter_by(engagement_id=engagement_id, slug=repository_slug)
                      .filter(models.Repository.deleted_at.is_(None)).one())
    branch = None
    if worktree is not None:
        branch = _git(worktree, "rev-parse", "--abbrev-ref", "HEAD")
        if base_commit:
            base_commit = _git(worktree, "rev-parse", base_commit)
    run = models.EngineRun(
        engagement_id=engagement_id, repository_id=repository.id if repository else None, label=label,
        provider=provider, organisation=organisation, signed_in_identity=identity, model=model,
        engine_version=engine_version, host=host, worktree_path=str(worktree) if worktree else None,
        branch=branch, base_commit=base_commit,
        inputs=input_hashes(worktree, runbook) if worktree is not None else [],
    )
    db.add(run)
    db.flush()
    return run


def _run(db: Session, engagement_id: str, label: str) -> models.EngineRun:
    run = db.query(models.EngineRun).filter_by(engagement_id=engagement_id, label=label).one_or_none()
    if run is None:
        raise LookupError(f"no engine run {label} in {engagement_id}; start it first")
    return run


def intervene(db: Session, engagement_id: str, label: str, stage: str, what: str) -> models.EngineRun:
    run = _run(db, engagement_id, label)
    run.interventions = [*run.interventions, {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                                              "stage": stage, "what": what}]
    db.flush()
    return run


PROTOCOL_ACTIONS = ("ctrl-c",)


def protocol(db: Session, engagement_id: str, label: str, action: str, why: str) -> models.EngineRun:
    """A step the runbook prescribes, identically in both arms: recorded, never counted as an intervention."""
    if action not in PROTOCOL_ACTIONS:
        raise ValueError(f"action must be one of {', '.join(PROTOCOL_ACTIONS)}")
    run = _run(db, engagement_id, label)
    run.protocol_actions = [*run.protocol_actions, {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                                                    "action": action, "why": why}]
    db.flush()
    return run


def mark_pilot(db: Session, engagement_id: str, label: str, why: str) -> models.EngineRun:
    """The run is the pilot: kept and verified, excluded from the experiment's comparison."""
    run = _run(db, engagement_id, label)
    run.role, run.role_reason = "pilot", why
    db.flush()
    return run


def finish(db: Session, engagement_id: str, label: str, outcome: str, elapsed_minutes: int | None = None,
           premium_requests: int | None = None, transcript: Path | None = None, notes: str | None = None) -> models.EngineRun:
    run = _run(db, engagement_id, label)
    if outcome not in models.ENGINE_RUN_OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(models.ENGINE_RUN_OUTCOMES)}")
    run.outcome = outcome
    run.finished_at = datetime.datetime.now(datetime.timezone.utc)
    run.elapsed_minutes = elapsed_minutes
    run.premium_requests = premium_requests
    run.notes = notes
    if transcript is not None:
        run.transcript = {"path": str(transcript), "sha256": _sha256(transcript)}
    if run.worktree_path:
        run.head_commit = _git(Path(run.worktree_path), "rev-parse", "HEAD")
    db.flush()
    return run


def as_dict(run: models.EngineRun) -> dict:
    return {
        "label": run.label, "engagement": run.engagement_id, "provider": run.provider,
        "organisation": run.organisation, "signedInIdentity": run.signed_in_identity, "model": run.model,
        "engineVersion": run.engine_version, "host": run.host, "branch": run.branch, "baseCommit": run.base_commit,
        "headCommit": run.head_commit, "worktree": run.worktree_path, "inputs": run.inputs,
        "startedAt": run.started_at.isoformat() if run.started_at else None,
        "finishedAt": run.finished_at.isoformat() if run.finished_at else None, "outcome": run.outcome,
        "elapsedMinutes": run.elapsed_minutes, "premiumRequests": run.premium_requests,
        "interventions": run.interventions, "protocolActions": run.protocol_actions, "transcript": run.transcript,
        "notes": run.notes, "role": run.role, "roleReason": run.role_reason,
    }


def main(argv: list[str] | None = None) -> int:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(prog="python -m app.engine.runs", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("start")
    s.add_argument("--engagement", required=True)
    s.add_argument("--repository")
    s.add_argument("--label", required=True)
    s.add_argument("--worktree", type=Path)
    s.add_argument("--base")
    s.add_argument("--provider", required=True, choices=sorted(boundary.PROVIDERS))
    s.add_argument("--organisation", required=True)
    s.add_argument("--identity", required=True)
    s.add_argument("--model", required=True)
    s.add_argument("--engine-version", required=True)
    s.add_argument("--host")
    s.add_argument("--runbook", type=Path)
    i = sub.add_parser("intervene")
    i.add_argument("--engagement", required=True)
    i.add_argument("--label", required=True)
    i.add_argument("--stage", required=True)
    i.add_argument("--what", required=True)
    f = sub.add_parser("finish")
    f.add_argument("--engagement", required=True)
    f.add_argument("--label", required=True)
    f.add_argument("--outcome", required=True, choices=models.ENGINE_RUN_OUTCOMES)
    f.add_argument("--elapsed-minutes", type=int)
    f.add_argument("--premium-requests", type=int)
    f.add_argument("--transcript", type=Path)
    f.add_argument("--notes")
    p = sub.add_parser("protocol", help="a step the runbook prescribes in both arms; not an intervention")
    p.add_argument("--engagement", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--action", required=True, choices=PROTOCOL_ACTIONS)
    p.add_argument("--why", required=True)
    m = sub.add_parser("mark-pilot", help="keep the run and verify it, excluded from the comparison")
    m.add_argument("--engagement", required=True)
    m.add_argument("--label", required=True)
    m.add_argument("--why", required=True)
    w = sub.add_parser("show")
    w.add_argument("--engagement", required=True)
    w.add_argument("--label")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.command == "start":
            run = start(db, engagement_id=args.engagement, label=args.label, provider=args.provider,
                        organisation=args.organisation, identity=args.identity, model=args.model,
                        engine_version=args.engine_version, host=args.host, repository_slug=args.repository,
                        worktree=args.worktree, base_commit=args.base, runbook=args.runbook)
        elif args.command == "intervene":
            run = intervene(db, args.engagement, args.label, args.stage, args.what)
        elif args.command == "protocol":
            run = protocol(db, args.engagement, args.label, args.action, args.why)
        elif args.command == "mark-pilot":
            run = mark_pilot(db, args.engagement, args.label, args.why)
        elif args.command == "finish":
            run = finish(db, args.engagement, args.label, args.outcome, args.elapsed_minutes, args.premium_requests,
                         args.transcript, args.notes)
        else:
            q = db.query(models.EngineRun).filter_by(engagement_id=args.engagement)
            if args.label:
                q = q.filter_by(label=args.label)
            print(json.dumps([as_dict(r) for r in q.order_by(models.EngineRun.label)], indent=2))
            return 0
        db.commit()
        print(json.dumps(as_dict(run), indent=2))
        return 0
    except (boundary.EngineNotAllowed, boundary.CredentialRefused, LookupError, ValueError) as err:
        db.rollback()
        print(f"STOP. {err}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
