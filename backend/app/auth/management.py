"""Disabling, enabling and deleting users, and removing one machine from a user's registration: an admin's actions
(docs/VDI-SETUP.md, "Users and sign-in").

- Disabling takes effect at once: the user's open sessions end, and signing in is refused with a plain message. Their
  history and the repositories they own stay; an admin may reassign those at any time. Enabling restores access.
- Deleting is refused while the user owns any repository: each needs a new owner first, and the refusal lists them.
  The user's row goes; the activity record keeps their name against everything they did (`actor`), and its link to
  the row becomes empty.
- Nobody disables or deletes themselves, and nobody disables or deletes the last admin.

Every action is recorded (app.auth.activity) with who did it and when, and has a command-line equivalent
(python -m app.users disable / enable / delete / remove-machine).
"""
import datetime

from sqlalchemy.orm import Session

from app import models
from app.auth import activity, machine, service
from app.auth import actor as actors
from app.auth.service import Refused


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def owned_repositories(db: Session, user: models.User) -> list[tuple[models.Repository, str]]:
    """The repositories the user owns (not deleted), each with its engagement's name, by engagement and name."""
    rows = (db.query(models.Repository, models.Engagement.client_name)
            .join(models.Engagement, models.Engagement.id == models.Repository.engagement_id)
            .filter(models.Repository.owner_user_id == user.id, models.Repository.deleted_at.is_(None))
            .order_by(models.Engagement.client_name, models.Repository.name).all())
    return [(repository, engagement) for repository, engagement in rows]


def describe_owned(owned: list[tuple[models.Repository, str]]) -> str:
    return "; ".join(f"{repository.name} ({engagement})" for repository, engagement in owned)


def _check(db: Session, user: models.User, admin: actors.Actor, what: str) -> None:
    """An admin, acting on someone else, never leaving no admin."""
    if not admin.is_admin:
        raise Refused(f"Only an admin may {what} a user.", "NOT_ALLOWED")
    if admin.user_id == user.id:
        raise Refused(f"You cannot {what} yourself: ask another admin.", "SELF")
    if user.role == actors.ADMIN and user.deactivated_at is None and service._last_admin(db, user):
        raise Refused(f"{user.name} is the last admin: make another user an admin first.", "LAST_ADMIN")


def disable(db: Session, user: models.User, admin: actors.Actor) -> list[tuple[models.Repository, str]]:
    """Ends their sessions and refuses their sign-in from now on. Returns the repositories they own, which stay
    theirs until an admin reassigns them. The caller commits."""
    _check(db, user, admin, "disable")
    if user.deactivated_at is not None:
        raise Refused(f"{user.name} is disabled already.", "ALREADY_DISABLED")
    user.deactivated_at = user.updated_at = _now()
    service.end_sessions(db, user)
    owned = owned_repositories(db, user)
    db.flush()
    summary = f"Disabled {user.name} ({user.login})" + (f"; owns {describe_owned(owned)}" if owned else "")
    activity.record(db, "disable_user", "user", str(user.id), summary, actor=admin)
    return owned


def enable(db: Session, user: models.User, admin: actors.Actor) -> None:
    if not admin.is_admin:
        raise Refused("Only an admin may enable a user.", "NOT_ALLOWED")
    if user.deactivated_at is None:
        raise Refused(f"{user.name} is enabled already.", "ALREADY_ENABLED")
    user.deactivated_at = None
    user.updated_at = _now()
    db.flush()
    activity.record(db, "enable_user", "user", str(user.id), f"Enabled {user.name} ({user.login})", actor=admin)


def delete(db: Session, user: models.User, admin: actors.Actor) -> None:
    """Refused while they own a repository. Their machines, sessions and requests go with them; the activity record
    keeps their name. The caller commits."""
    _check(db, user, admin, "delete")
    owned = owned_repositories(db, user)
    if owned:
        raise Refused(f"{user.name} owns {len(owned)} repositor{'y' if len(owned) == 1 else 'ies'}: assign each a new "
                      f"owner first: {describe_owned(owned)}.", "OWNS_REPOSITORIES")
    activity.record(db, "delete_user", "user", str(user.id),
                    f"Deleted {user.name} ({user.login}, {user.windows_account})", actor=admin)
    db.delete(user)
    db.flush()


def remove_machine(db: Session, user: models.User, admin: actors.Actor, host: str) -> None:
    """Removes one machine from their registration; their sessions there end. Their last machine stays: disable them
    instead."""
    if not admin.is_admin:
        raise Refused("Only an admin may remove a user's machine.", "NOT_ALLOWED")
    if admin.user_id == user.id and machine.same(host, admin.hostname or ""):
        raise Refused(f"You cannot remove the machine you are signed in on ({host}): ask another admin.", "SELF")
    rows = db.query(models.UserHost).filter_by(user_id=user.id).all()
    row = next((r for r in rows if machine.same(r.hostname, host)), None)
    if row is None:
        raise Refused(f"{user.name} is not registered for {host}.", "NOT_FOUND")
    if len(rows) == 1:
        raise Refused(f"{host} is {user.name}'s only machine: disable them instead.", "LAST_MACHINE")
    db.delete(row)
    for session in db.query(models.UserSession).filter(models.UserSession.user_id == user.id,
                                                       models.UserSession.ended_at.is_(None)):
        if machine.same(session.hostname, host):
            session.ended_at = _now()
    user.updated_at = _now()
    db.flush()
    activity.record(db, "remove_user_machine", "user", str(user.id), f"Removed {row.hostname} from {user.name}'s machines",
                    actor=admin)
