"""Access requests (docs/VDI-SETUP.md, "Users and sign-in"): a person asks for access from the sign-in page of their own
platform, and an admin approves or rejects it.

- Someone not registered gives their name and chooses a password. Their Windows account and machine are this
  platform's, taken from the machine (app.auth.machine), never typed; their sign-in name is their Windows user name.
- A registered user on a machine their registration does not name asks, with their password, to add that machine.
- At most one request per Windows account is pending. Until an admin approves it, the requester reaches nothing; the
  sign-in page says it is pending, or that it was rejected and why.
- Approving grants the developer role, always. Making someone an admin is a separate action of an admin's
  (`promote`), recorded. The first admin is created once per installation (python -m app.users create-first-admin);
  after that nobody becomes an admin any other way.

Every request, approval, rejection and promotion is recorded (app.auth.activity): who, from which machine, when.
"""
import datetime
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.auth import activity, passwords, service
from app.auth import actor as actors
from app.auth.service import Refused

ACCESS, MACHINE = "access", "machine"
PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _requester(request: models.AccessRequest) -> actors.Actor:
    """The person asking, for the activity record: not a user yet (or, for a machine, not on this machine yet)."""
    return actors.Actor(request.user_id, request.login, f"{request.name}, {request.windows_account}", actors.DEVELOPER,
                        request.hostname)


def pending(db: Session, account: str) -> models.AccessRequest | None:
    return (db.query(models.AccessRequest)
            .filter(func.lower(models.AccessRequest.windows_account) == account.strip().lower(),
                    models.AccessRequest.status == PENDING).one_or_none())


def latest(db: Session, account: str, host: str) -> models.AccessRequest | None:
    """This account's newest request: for access, or to add this machine."""
    query = db.query(models.AccessRequest).filter(
        func.lower(models.AccessRequest.windows_account) == account.strip().lower())
    rows = query.order_by(models.AccessRequest.requested_at.desc()).all()
    return next((r for r in rows if r.kind == ACCESS or r.hostname.lower() == host.strip().lower()), None)


def pending_count(db: Session) -> int:
    return db.query(models.AccessRequest).filter(models.AccessRequest.status == PENDING).count()


def _login_for(db: Session, account: str) -> str:
    """The Windows user name, lower case: what they sign in with. Numbered when someone has it already."""
    base = re.sub(r"[^a-z0-9._-]", "", account.split("\\")[-1].strip().lower()) or "user"
    login, n = base, 1
    while service.by_login(db, login) is not None:
        n += 1
        login = f"{base}{n}"
    return login


def request_access(db: Session, *, name: str, password: str, account: str, host: str) -> models.AccessRequest:
    """A request from this machine, under this Windows account. Refused, with a plain message, when nobody can approve
    it yet, when one is pending already, or when there is nothing to ask for. The caller commits."""
    if not service.admins_exist(db):
        raise Refused("Nobody is registered yet: the first admin is created once, on the machine where the platform is "
                      "installed (python -m app.users create-first-admin), and approves everyone else.", "FIRST_ADMIN_NEEDED")
    waiting = pending(db, account)
    if waiting is not None:
        raise Refused(f"A request from {waiting.windows_account} is waiting already, since "
                      f"{waiting.requested_at:%Y-%m-%d %H:%M} UTC: an admin approves or rejects it.", "REQUEST_PENDING")
    user = service.by_account(db, account)
    if user is not None:
        if user.deactivated_at is not None:
            raise Refused(f"{user.name}'s registration is deactivated: ask an admin to reactivate it.", "DEACTIVATED")
        if any(h.lower() == host.strip().lower() for h in service.hosts(db, user)):
            raise Refused(f"You are registered for this machine ({host}) already: sign in as '{user.login}'.",
                          "ALREADY_REGISTERED")
        if not passwords.verify(password, user.password_hash):
            raise Refused(f"You are registered as '{user.login}' on other machines: give your password to ask for this "
                          f"one ({host}) to be added.", "WRONG_PASSWORD")
        row = models.AccessRequest(kind=MACHINE, windows_account=user.windows_account, hostname=host.strip(),
                                   name=user.name, login=user.login, user_id=user.id)
    else:
        name = name.strip()
        if not name:
            raise Refused("Give your full name.", "INVALID_USER")
        if why := passwords.weakness(password):
            raise Refused(why, "WEAK_PASSWORD")
        if "\\" not in account:
            raise Refused(f"This platform runs as '{account}', which is not a Windows account (DOMAIN\\user).",
                          "INVALID_ACCOUNT")
        row = models.AccessRequest(kind=ACCESS, windows_account=account.strip(), hostname=host.strip(), name=name,
                                   login=_login_for(db, account), password_hash=passwords.hash_password(password))
    db.add(row)
    db.flush()
    what = "access" if row.kind == ACCESS else f"machine {row.hostname} added"
    activity.record(db, "request_access", "access_request", str(row.id), f"Asked for {what}", actor=_requester(row))
    return row


def _decidable(request: models.AccessRequest) -> None:
    if request.status != PENDING:
        raise Refused(f"This request was {request.status} already, {request.decided_at:%Y-%m-%d %H:%M} UTC.", "DECIDED")


def approve(db: Session, request: models.AccessRequest, admin: actors.Actor) -> models.User:
    """Grants it: a new developer (never an admin), or the machine added to their registration. The caller commits."""
    if not admin.is_admin:
        raise Refused("Only an admin approves access requests.", "NOT_ALLOWED")
    _decidable(request)
    if request.kind == ACCESS:
        if service.by_account(db, request.windows_account) is not None:
            raise Refused(f"The Windows account {request.windows_account} is registered to a user already.", "ACCOUNT_TAKEN")
        login = request.login if service.by_login(db, request.login) is None else _login_for(db, request.windows_account)
        user = models.User(login=login, name=request.name, windows_account=request.windows_account,
                           role=actors.DEVELOPER, password_hash=request.password_hash, must_change_password=False)
        db.add(user)
        db.flush()
        db.add(models.UserHost(user_id=user.id, hostname=request.hostname))
        request.user_id, request.login = user.id, login
        summary = f"Approved {request.name}'s access, as a developer, on {request.hostname}"
    else:
        user = db.get(models.User, request.user_id)
        if user is None or user.deactivated_at is not None:
            raise Refused("That user is no longer registered, or is deactivated.", "NOT_FOUND")
        if not any(h.lower() == request.hostname.lower() for h in service.hosts(db, user)):
            db.add(models.UserHost(user_id=user.id, hostname=request.hostname))
        summary = f"Added {request.hostname} to {user.name}'s machines"
    request.password_hash = None
    request.status, request.decided_at, request.decided_by_user_id = APPROVED, _now(), admin.user_id
    db.flush()
    activity.record(db, "approve_access_request", "access_request", str(request.id), summary, actor=admin)
    return user


def reject(db: Session, request: models.AccessRequest, admin: actors.Actor, reason: str | None) -> None:
    if not admin.is_admin:
        raise Refused("Only an admin rejects access requests.", "NOT_ALLOWED")
    _decidable(request)
    request.password_hash = None
    request.status, request.decided_at, request.decided_by_user_id = REJECTED, _now(), admin.user_id
    request.reason = (reason or "").strip() or None
    db.flush()
    activity.record(db, "reject_access_request", "access_request", str(request.id),
                    f"Rejected {request.name}'s request" + (f": {request.reason}" if request.reason else ""), actor=admin)


def promote(db: Session, user: models.User, admin: actors.Actor) -> None:
    """Makes another user an admin: an admin's action, recorded. The only way anyone but the first admin becomes one."""
    if not admin.is_admin:
        raise Refused("Only an admin makes another user an admin.", "NOT_ALLOWED")
    if user.deactivated_at is not None:
        raise Refused(f"{user.name} is deactivated: reactivate them first.", "DEACTIVATED")
    if user.role == actors.ADMIN:
        raise Refused(f"{user.name} is an admin already.", "ALREADY_ADMIN")
    user.role = actors.ADMIN
    user.updated_at = _now()
    db.flush()
    activity.record(db, "promote_user", "user", str(user.id), f"Made {user.name} an admin", actor=admin)
