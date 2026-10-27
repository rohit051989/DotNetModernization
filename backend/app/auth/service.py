"""Users, sign-in and sessions.

Signing in requires three things to match the user's registration: the password, the Windows account the local
backend runs under, and this machine's hostname. A session is a random token in an HttpOnly cookie, stored only as
its SHA-256; it ends at sign-out or after SESSION_IDLE_MINUTES without a request. A password reset by an admin is
temporary: the user sets a new one at their next sign-in.

Command-line tools act as the registered user whose Windows account and machine run them (`cli_actor`).
"""
import datetime
import hashlib
import secrets


from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.auth import actor as actors
from app.auth import machine, passwords
from app.config import settings

COOKIE = "mp_session"
TOUCH_EVERY = datetime.timedelta(seconds=30)


class Refused(Exception):
    """Sign-in, or a user change, refused: `message` says why in plain words; `code` is for callers."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.message, self.code = message, code


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------- users ----------


def by_login(db: Session, login: str) -> models.User | None:
    return db.query(models.User).filter(func.lower(models.User.login) == login.strip().lower()).one_or_none()


def by_account(db: Session, account: str) -> models.User | None:
    return db.query(models.User).filter(func.lower(models.User.windows_account) == account.strip().lower()).one_or_none()


def hosts(db: Session, user: models.User) -> list[str]:
    return sorted((h.hostname for h in db.query(models.UserHost).filter_by(user_id=user.id)), key=str.lower)


def admins_exist(db: Session) -> bool:
    return db.query(models.User).filter(models.User.role == actors.ADMIN, models.User.deactivated_at.is_(None)).count() > 0


def _clean_hosts(names: list[str]) -> list[str]:
    seen, out = set(), []
    for name in names:
        name = name.strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    if not out:
        raise Refused("Name at least one machine (hostname) the user signs in from.", "NO_HOSTS")
    return out


def _check_account(account: str) -> str:
    account = account.strip()
    if "\\" not in account or account.startswith("\\") or account.endswith("\\"):
        raise Refused(f"'{account}' is not a Windows account: write it as DOMAIN\\user.", "INVALID_ACCOUNT")
    return account


def create_user(db: Session, *, login: str, name: str, windows_account: str, role: str, host_names: list[str],
                password: str, must_change_password: bool = True) -> models.User:
    """Registers a user. The password is temporary unless must_change_password is False (the first admin)."""
    login, name = login.strip(), name.strip()
    if not login or not name:
        raise Refused("A user needs a sign-in name and a full name.", "INVALID_USER")
    if role not in actors.ROLES:
        raise Refused(f"A role is one of {', '.join(actors.ROLES)}.", "INVALID_ROLE")
    windows_account = _check_account(windows_account)
    if by_login(db, login):
        raise Refused(f"The sign-in name '{login}' is taken.", "LOGIN_TAKEN")
    if by_account(db, windows_account):
        raise Refused(f"The Windows account {windows_account} is registered to another user already.", "ACCOUNT_TAKEN")
    if why := passwords.weakness(password):
        raise Refused(why, "WEAK_PASSWORD")
    user = models.User(login=login, name=name, windows_account=windows_account, role=role,
                       password_hash=passwords.hash_password(password), must_change_password=must_change_password)
    db.add(user)
    db.flush()
    for host in _clean_hosts(host_names):
        db.add(models.UserHost(user_id=user.id, hostname=host))
    db.flush()
    return user


def update_user(db: Session, user: models.User, *, name: str | None = None, role: str | None = None,
                windows_account: str | None = None, host_names: list[str] | None = None,
                active: bool | None = None) -> models.User:
    if name is not None:
        user.name = name.strip() or user.name
    if role is not None:
        if role not in actors.ROLES:
            raise Refused(f"A role is one of {', '.join(actors.ROLES)}.", "INVALID_ROLE")
        if role == actors.ADMIN and user.role != actors.ADMIN:
            raise Refused("Making someone an admin is an action of its own: promote them (app.auth.requests.promote).",
                          "PROMOTE_SEPARATELY")
        if user.role == actors.ADMIN and role != actors.ADMIN and _last_admin(db, user):
            raise Refused("This is the last admin: make another user an admin first.", "LAST_ADMIN")
        user.role = role
    if windows_account is not None:
        windows_account = _check_account(windows_account)
        other = by_account(db, windows_account)
        if other is not None and other.id != user.id:
            raise Refused(f"The Windows account {windows_account} is registered to another user already.", "ACCOUNT_TAKEN")
        user.windows_account = windows_account
    if host_names is not None:
        db.query(models.UserHost).filter_by(user_id=user.id).delete()
        for host in _clean_hosts(host_names):
            db.add(models.UserHost(user_id=user.id, hostname=host))
    if active is not None:
        if not active and user.role == actors.ADMIN and _last_admin(db, user):
            raise Refused("This is the last admin: make another user an admin first.", "LAST_ADMIN")
        user.deactivated_at = None if active else _now()
        if not active:
            end_sessions(db, user)
    user.updated_at = _now()
    db.flush()
    return user


def _last_admin(db: Session, user: models.User) -> bool:
    return db.query(models.User).filter(models.User.role == actors.ADMIN, models.User.deactivated_at.is_(None),
                                        models.User.id != user.id).count() == 0


def reset_password(db: Session, user: models.User, temporary: str) -> None:
    """An admin's reset: the password works once, to set a new one. Every session of the user ends."""
    if why := passwords.weakness(temporary):
        raise Refused(why, "WEAK_PASSWORD")
    user.password_hash = passwords.hash_password(temporary)
    user.must_change_password = True
    user.updated_at = _now()
    end_sessions(db, user)
    db.flush()


def change_password(db: Session, user: models.User, current: str, new: str) -> None:
    if not passwords.verify(current, user.password_hash):
        raise Refused("The current password is wrong.", "WRONG_PASSWORD")
    _set_new(user, new, current)
    db.flush()


def _set_new(user: models.User, new: str, current: str) -> None:
    if why := passwords.weakness(new):
        raise Refused(why, "WEAK_PASSWORD")
    if new == current:
        raise Refused("The new password must differ from the old one.", "SAME_PASSWORD")
    user.password_hash = passwords.hash_password(new)
    user.must_change_password = False
    user.updated_at = _now()


# ---------- sign-in and sessions ----------


def registration_problem(db: Session, user: models.User, account: str, host: str) -> str | None:
    """Why this user may not sign in on this machine under this Windows account, or None."""
    if not machine.same(user.windows_account, account):
        return (f"This account is registered for the Windows account {user.windows_account}, and this platform runs as "
                f"{account}. Sign in to Windows as yourself and start your own platform, or ask the admin.")
    if not any(machine.same(h, host) for h in hosts(db, user)):
        return f"This account is not registered for this machine ({host}) — ask the admin."
    return None


def sign_in(db: Session, login: str, password: str, new_password: str | None = None, *,
            account: str | None = None, host: str | None = None) -> tuple[str, models.User]:
    """(the session token for the cookie, the user). Refused, with a plain message, unless the password, the Windows
    account and the machine all match the registration."""
    account = account or machine.windows_account()
    host = host or machine.hostname()
    user = by_login(db, login)
    if user is None or user.deactivated_at is not None or not passwords.verify(password, user.password_hash):
        raise Refused("The sign-in name or password is wrong.", "WRONG_PASSWORD")
    if problem := registration_problem(db, user, account, host):
        raise Refused(problem, "NOT_REGISTERED_HERE")
    if user.must_change_password:
        if not new_password:
            raise Refused("Your password was set by an admin: choose a new one to sign in.", "PASSWORD_CHANGE_REQUIRED")
        _set_new(user, new_password, password)
    token = secrets.token_urlsafe(32)
    db.add(models.UserSession(token_hash=_token_hash(token), user_id=user.id, hostname=host, windows_account=account))
    db.flush()
    return token, user


def resolve(db: Session, token: str | None, host: str | None = None) -> tuple[models.User, models.UserSession] | None:
    """The user and session of a cookie, when it is live; touches it. None when signed out or expired."""
    if not token:
        return None
    session = db.query(models.UserSession).filter_by(token_hash=_token_hash(token)).one_or_none()
    if session is None or session.ended_at is not None:
        return None
    now = _now()
    if now - session.last_seen_at > datetime.timedelta(minutes=settings.session_idle_minutes):
        session.ended_at = now
        return None
    if host and not machine.same(session.hostname, host):
        return None
    user = db.get(models.User, session.user_id)
    if user is None or user.deactivated_at is not None:
        return None
    if now - session.last_seen_at > TOUCH_EVERY:
        session.last_seen_at = now
    return user, session


def sign_out(db: Session, token: str | None) -> None:
    if not token:
        return
    session = db.query(models.UserSession).filter_by(token_hash=_token_hash(token)).one_or_none()
    if session is not None and session.ended_at is None:
        session.ended_at = _now()


def end_sessions(db: Session, user: models.User) -> None:
    db.query(models.UserSession).filter(models.UserSession.user_id == user.id,
                                        models.UserSession.ended_at.is_(None)).update({"ended_at": _now()})


def live_session_by_host(db: Session) -> dict[str, models.User]:
    """The user most recently active on each machine, among live sessions."""
    cutoff = _now() - datetime.timedelta(minutes=settings.session_idle_minutes)
    found: dict[str, models.User] = {}
    for session in (db.query(models.UserSession)
                    .filter(models.UserSession.ended_at.is_(None), models.UserSession.last_seen_at > cutoff)
                    .order_by(models.UserSession.last_seen_at)):
        found[session.hostname.lower()] = db.get(models.User, session.user_id)
    return found


# ---------- command-line tools ----------


class NotRegistered(SystemExit):
    pass


def cli_actor(db: Session, *, admin: bool = False) -> actors.Actor:
    """The registered user this command acts as: the one whose Windows account and machine run it. Refuses
    otherwise (and, with `admin`, unless that user is an admin). Sets it as the current actor."""
    account, host = machine.windows_account(), machine.hostname()
    user = by_account(db, account)
    if user is None or user.deactivated_at is not None:
        raise NotRegistered(f"No user is registered for the Windows account {account}, so this command cannot act as "
                            f"anyone — ask the admin to register you (docs/VDI-SETUP.md, \"Users and sign-in\").")
    if not any(machine.same(h, host) for h in hosts(db, user)):
        raise NotRegistered(f"{user.name} is not registered for this machine ({host}) — ask the admin.")
    if admin and user.role != actors.ADMIN:
        raise NotRegistered(f"This command is for admins, and {user.name} is a {user.role}.")
    current = actors.of(user, host)
    actors.set_current(current)
    return current


