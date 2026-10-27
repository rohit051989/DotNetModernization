"""Who did what, from which machine. Every API call that changes something is recorded when it succeeds
(app.auth.http), named by its route and subject; command-line tools record their actions here too. Actions from
before sign-in existed are recorded with the actor 'before sign-in' (migration f3a7c2e9d5b1)."""
import contextvars

from sqlalchemy.orm import Session

from app import models
from app.auth import actor as actors

# A route's path parameter, and the kind of record it names, most specific first.
SUBJECTS = (
    ("resolution_id", "item_resolution"),
    ("target_state_id", "target_state"),
    ("decision_id", "decision"),
    ("execution_id", "job_execution"),
    ("repository_id", "repository"),
    ("item_id", "catalog_item"),
    ("pattern_id", "pattern"),
    ("user_id", "user"),
    ("job_name", "job"),
    ("step_name", "step"),
    ("name", "extractor"),
    ("host", "endpoint_annotation"),
    ("engagement_id", "engagement"),
)


# The record a call changed, when its path does not name it (a decision upserted by engagement and pattern): the guard
# hands each call a holder, and the route says what it changed (`about`). A holder, not the variable itself, so a
# synchronous route on the thread pool, which runs in a copy of the context, still reaches it.
_about: contextvars.ContextVar[dict | None] = contextvars.ContextVar("activity_about", default=None)


def about(subject_type: str, subject_id) -> None:
    holder = _about.get()
    if holder is not None:
        holder["subject"] = (subject_type, str(subject_id))


def collect() -> tuple[dict, contextvars.Token]:
    holder: dict = {}
    return holder, _about.set(holder)


def release(token: contextvars.Token) -> None:
    _about.reset(token)


def subject_of(path_params: dict) -> tuple[str | None, str | None]:
    for param, kind in SUBJECTS:
        if param in path_params:
            return kind, str(path_params[param])
    return None, None


def record(db: Session, action: str, subject_type: str | None = None, subject_id: str | None = None,
           summary: str | None = None, actor: actors.Actor | None = None) -> models.ActivityRecord:
    """Adds one record for the acting person (the current actor, else the platform itself). Flushes; the caller
    commits."""
    who = actor or actors.current() or actors.SYSTEM
    row = models.ActivityRecord(user_id=who.user_id, actor=who.label(), hostname=who.hostname, action=action,
                                subject_type=subject_type, subject_id=subject_id, summary=summary)
    db.add(row)
    db.flush()
    return row


def last(db: Session, subject_type: str, subject_id: str) -> models.ActivityRecord | None:
    return (db.query(models.ActivityRecord)
            .filter_by(subject_type=subject_type, subject_id=str(subject_id))
            .order_by(models.ActivityRecord.at.desc(), models.ActivityRecord.id.desc())
            .first())


def history(db: Session, subject_type: str, subject_id: str, limit: int = 50) -> list[models.ActivityRecord]:
    return (db.query(models.ActivityRecord)
            .filter_by(subject_type=subject_type, subject_id=str(subject_id))
            .order_by(models.ActivityRecord.at.desc(), models.ActivityRecord.id.desc())
            .limit(limit).all())


def describe(row: models.ActivityRecord | None) -> str:
    if row is None:
        return "someone"
    where = f" on {row.hostname}" if row.hostname else ""
    return f"{row.actor}{where}, at {row.at:%Y-%m-%d %H:%M} UTC"
