"""How long a step may run, and how long it may go without progress (rbc-release-5).

A default for every step, from the settings (STEP_TIMEOUT_SECONDS, 3600; STEP_STALL_SECONDS, 900), and overrides in the
database, changeable without code — the most specific wins:

    1. this step, for this repository
    2. every step, for this repository
    3. this step, for every repository
    4. the defaults

A row may set the time limit, the stall limit, or both; what it leaves empty comes from the next level down.

    python -m app.workflow.time_limits show [--repository <engagement>/<slug>]
    python -m app.workflow.time_limits set [--step <step>] [--repository <engagement>/<slug>] [--timeout <s>] [--stall <s>] [--note "..."]
    python -m app.workflow.time_limits clear [--step <step>] [--repository <engagement>/<slug>]
"""
import argparse
import sys
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.config import settings


def _row(db: Session, step: str | None, repository_id) -> models.StepTimeLimit | None:
    query = db.query(models.StepTimeLimit)
    query = query.filter(models.StepTimeLimit.step_name.is_(None) if step is None else models.StepTimeLimit.step_name == step)
    query = query.filter(models.StepTimeLimit.repository_id.is_(None) if repository_id is None
                         else models.StepTimeLimit.repository_id == repository_id)
    return query.one_or_none()


def effective(db: Session, step: str, repository_id) -> dict:
    """{"timeout_seconds", "stall_seconds", "timeout_from", "stall_from"} for `step` on `repository_id`."""
    levels = []
    if repository_id is not None:
        levels += [("this step, this repository", _row(db, step, repository_id)),
                   ("this repository", _row(db, None, repository_id))]
    levels.append(("this step", _row(db, step, None)))
    result = {"timeout_seconds": settings.step_timeout_seconds, "timeout_from": "default (STEP_TIMEOUT_SECONDS)",
              "stall_seconds": settings.step_stall_seconds, "stall_from": "default (STEP_STALL_SECONDS)",
              # Within the step: one project's load, one file's analysis (recorded "not checked" when over).
              "project_seconds": settings.step_project_seconds, "file_seconds": settings.step_file_seconds}
    for key in ("timeout_seconds", "stall_seconds"):
        for name, row in levels:
            if row is not None and getattr(row, key) is not None:
                result[key] = getattr(row, key)
                result[key.replace("_seconds", "_from")] = name
                break
    return result


def set_limit(db: Session, step: str | None, repository_id, timeout: int | None, stall: int | None,
              note: str | None = None) -> models.StepTimeLimit:
    if step is None and repository_id is None:
        raise ValueError("the defaults come from STEP_TIMEOUT_SECONDS and STEP_STALL_SECONDS in backend\\.env; "
                         "an override names a step, a repository, or both")
    for value in (timeout, stall):
        if value is not None and value <= 0:
            raise ValueError("limits are a number of seconds above 0")
    row = _row(db, step, repository_id) or models.StepTimeLimit(id=uuid.uuid4(), step_name=step, repository_id=repository_id)
    row.timeout_seconds, row.stall_seconds, row.note = timeout, stall, note
    db.add(row)
    db.flush()
    return row


def clear_limit(db: Session, step: str | None, repository_id) -> bool:
    """Empties an override, so the next level down applies. The row stays, with both limits empty (nothing is
    hard-deleted, CLAUDE.md rule 7); setting a limit again reuses it. False when there was nothing to clear."""
    row = _row(db, step, repository_id)
    if row is None or (row.timeout_seconds is None and row.stall_seconds is None):
        return False
    row.timeout_seconds = row.stall_seconds = None
    row.updated_at = func.now()
    db.flush()
    return True


def overrides(db: Session) -> list[models.StepTimeLimit]:
    """Every override that sets something, most general first."""
    rows = db.query(models.StepTimeLimit).filter(
        (models.StepTimeLimit.timeout_seconds.isnot(None)) | (models.StepTimeLimit.stall_seconds.isnot(None))).all()
    return sorted(rows, key=lambda r: (r.repository_id is not None, str(r.repository_id or ""), r.step_name or ""))


def _repository(db: Session, text: str | None):
    if not text:
        return None
    engagement, _, slug = text.partition("/")
    repo = db.query(models.Repository).filter_by(engagement_id=engagement, slug=slug).filter(
        models.Repository.deleted_at.is_(None)).one_or_none()
    if repo is None:
        raise SystemExit(f"no repository {text} (write it as <engagement>/<slug>)")
    return repo


def main(argv: list[str] | None = None) -> int:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(prog="python -m app.workflow.time_limits", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show")
    show.add_argument("--repository")
    for name in ("set", "clear"):
        p = sub.add_parser(name)
        p.add_argument("--step")
        p.add_argument("--repository")
        if name == "set":
            p.add_argument("--timeout", type=int)
            p.add_argument("--stall", type=int)
            p.add_argument("--note")
    args = parser.parse_args(argv)
    db = SessionLocal()
    try:
        repo = _repository(db, args.repository)
        repo_id = repo.id if repo else None
        if args.command == "set":
            set_limit(db, args.step, repo_id, args.timeout, args.stall, args.note)
            db.commit()
        elif args.command == "clear":
            print("cleared" if clear_limit(db, args.step, repo_id) else "nothing to clear")
            db.commit()
        print(f"Defaults: time limit {settings.step_timeout_seconds} s, stall limit {settings.step_stall_seconds} s")
        for row in overrides(db):
            where = db.get(models.Repository, row.repository_id) if row.repository_id else None
            print(f"  {row.step_name or 'every step'} on {f'{where.engagement_id}/{where.slug}' if where else 'every repository'}: "
                  f"time limit {row.timeout_seconds or '-'} s, stall limit {row.stall_seconds or '-'} s"
                  + (f" ({row.note})" if row.note else ""))
        if args.command == "show" and repo is not None:
            steps = [r.step_name for r in db.query(models.WfStepRegistration).filter(
                models.WfStepRegistration.deleted_at.is_(None)).order_by(models.WfStepRegistration.lifecycle_step_no)]
            print(f"In effect for {args.repository}:")
            for step in steps:
                e = effective(db, step, repo_id)
                print(f"  {step:36} {e['timeout_seconds']:>6} s ({e['timeout_from']}), stall {e['stall_seconds']} s ({e['stall_from']})")
        return 0
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
