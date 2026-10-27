"""Users (admins only, by app.auth.policy: every change here is an admin's), who is online, repository owners, and
the activity record."""
import datetime
import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import heartbeat, models
from app.auth import management, requests, service
from app.db import get_db
from app.errors import ErrorResponse, error

router = APIRouter(prefix="/api", tags=["Users"])


class UserOut(BaseModel):
    id: str
    login: str
    name: str
    windows_account: str
    role: str
    hosts: list[str]
    active: bool
    must_change_password: bool = Field(description="True after an admin set the password, until the user replaces it.")
    last_sign_in_at: datetime.datetime | None
    repositories_owned: int


class UserIn(BaseModel):
    login: str = Field(min_length=1, description="The name the person signs in with.")
    name: str = Field(min_length=1)
    windows_account: str = Field(min_length=3, description="DOMAIN\\user: the account their own platform runs under.")
    role: str = Field(default="developer", description="'developer', always: an admin makes someone an admin with "
                                                       "POST /api/users/{id}/promote, an action of its own.")
    hosts: list[str] = Field(min_length=1, description="The machines (hostnames) they sign in from.")
    temporary_password: str = Field(min_length=1, description="Works once: they choose their own at the first sign-in.")


class UserUpdate(BaseModel):
    name: str | None = None
    windows_account: str | None = None
    role: str | None = None
    hosts: list[str] | None = None
    active: bool | None = None


class ResetIn(BaseModel):
    temporary_password: str = Field(min_length=1)


class OnlineOut(BaseModel):
    host: str
    user_name: str | None = Field(description="The person most recently signed in on that machine; null if nobody is.")
    user_login: str | None
    since: datetime.datetime
    last_seen: datetime.datetime


class OwnerIn(BaseModel):
    owner_user_id: str | None = Field(description="The developer (or admin) who owns it; null to leave it ownerless.")


class OwnerOut(BaseModel):
    repository_id: str
    owner_user_id: str | None
    owner_name: str | None


class ActivityOut(BaseModel):
    at: datetime.datetime
    actor: str
    hostname: str | None
    action: str
    subject_type: str | None
    subject_id: str | None
    summary: str | None


def _out(db: Session, user: models.User) -> UserOut:
    last = db.query(func.max(models.UserSession.created_at)).filter_by(user_id=user.id).scalar()
    owned = db.query(models.Repository).filter(models.Repository.owner_user_id == user.id,
                                               models.Repository.deleted_at.is_(None)).count()
    return UserOut(id=str(user.id), login=user.login, name=user.name, windows_account=user.windows_account, role=user.role,
                   hosts=service.hosts(db, user), active=user.deactivated_at is None,
                   must_change_password=user.must_change_password, last_sign_in_at=last, repositories_owned=owned)


def _user(db: Session, user_id: str) -> models.User:
    try:
        user = db.get(models.User, uuid.UUID(user_id))
    except ValueError:
        user = None
    if user is None:
        raise error(404, f"No user '{user_id}'", code="NOT_FOUND")
    return user


def _refused(refused: service.Refused):
    return error(422, refused.message, code=refused.code)


@router.get("/users", response_model=list[UserOut], summary="Every registered user", operation_id="list_users")
def list_users(db: Session = Depends(get_db)):
    """Everyone signed in may see who is registered (repository owners are named everywhere); only admins change it."""
    return [_out(db, u) for u in db.query(models.User).order_by(func.lower(models.User.name))]


@router.post("/users", response_model=UserOut, status_code=201, summary="Register a user", operation_id="create_user",
             responses={422: {"model": ErrorResponse, "description": "A field is invalid or already taken."}})
def create_user(payload: UserIn, db: Session = Depends(get_db)):
    """Admins only. The temporary password works once: the user sets their own at the first sign-in. Registers a
    developer: making someone an admin is promote's, a separate action."""
    if payload.role != "developer":
        raise error(422, "A new user is a developer: make them an admin afterwards with Make admin (promote), an action "
                         "of its own.", field="role", code="PROMOTE_SEPARATELY")
    try:
        user = service.create_user(db, login=payload.login, name=payload.name, windows_account=payload.windows_account,
                                   role=payload.role, host_names=payload.hosts, password=payload.temporary_password)
    except service.Refused as refused:
        raise _refused(refused) from None
    db.commit()
    return _out(db, user)


@router.put("/users/{user_id}", response_model=UserOut, summary="Change a user", operation_id="update_user",
            responses={404: {"model": ErrorResponse, "description": "No such user."}})
def update_user(user_id: str, payload: UserUpdate, request: Request, db: Session = Depends(get_db)):
    """Admins only. Only the fields sent change. `active` disables or enables them, as POST .../disable and
    .../enable do, with the same rules."""
    user = _user(db, user_id)
    try:
        service.update_user(db, user, name=payload.name, role=payload.role, windows_account=payload.windows_account,
                            host_names=payload.hosts)
        if payload.active is not None and payload.active != (user.deactivated_at is None):
            if payload.active:
                management.enable(db, user, request.state.actor)
            else:
                management.disable(db, user, request.state.actor)
    except service.Refused as refused:
        db.rollback()
        raise _refused(refused) from None
    db.commit()
    return _out(db, user)


class OwnedRepositoryOut(BaseModel):
    id: str
    name: str
    engagement_id: str
    engagement_name: str


class DisabledOut(BaseModel):
    user: UserOut
    owned_repositories: list[OwnedRepositoryOut] = Field(description="Still theirs: an admin may reassign each at any "
                                                                      "time (PUT /api/repositories/{id}/owner).")


def _owned_out(owned) -> list[OwnedRepositoryOut]:
    return [OwnedRepositoryOut(id=str(r.id), name=r.name, engagement_id=r.engagement_id, engagement_name=e) for r, e in owned]


_MANAGE_RESPONSES = {404: {"model": ErrorResponse, "description": "No such user."},
                     409: {"model": ErrorResponse, "description": "Refused: yourself, the last admin, owned "
                                                                  "repositories, or nothing to change; the message says which."}}


@router.get("/users/{user_id}/repositories", response_model=list[OwnedRepositoryOut],
            summary="The repositories a user owns", operation_id="list_user_repositories",
            responses={404: {"model": ErrorResponse, "description": "No such user."}})
def list_user_repositories(user_id: str, db: Session = Depends(get_db)):
    """What disabling leaves with them, and what must be reassigned before they can be deleted."""
    return _owned_out(management.owned_repositories(db, _user(db, user_id)))


@router.post("/users/{user_id}/disable", response_model=DisabledOut, summary="Disable a user",
             operation_id="disable_user", responses=_MANAGE_RESPONSES)
def disable_user(user_id: str, request: Request, db: Session = Depends(get_db)):
    """Admins only. At once: their sessions end and their sign-in is refused. Their history and repositories stay.
    Never yourself, nor the last admin."""
    user = _user(db, user_id)
    try:
        owned = management.disable(db, user, request.state.actor)
    except service.Refused as refused:
        db.rollback()
        raise error(409, refused.message, code=refused.code) from None
    db.commit()
    return DisabledOut(user=_out(db, user), owned_repositories=_owned_out(owned))


@router.post("/users/{user_id}/enable", response_model=UserOut, summary="Enable a disabled user",
             operation_id="enable_user", responses=_MANAGE_RESPONSES)
def enable_user(user_id: str, request: Request, db: Session = Depends(get_db)):
    """Admins only. They may sign in again."""
    user = _user(db, user_id)
    try:
        management.enable(db, user, request.state.actor)
    except service.Refused as refused:
        db.rollback()
        raise error(409, refused.message, code=refused.code) from None
    db.commit()
    return _out(db, user)


@router.delete("/users/{user_id}", status_code=204, summary="Delete a user", operation_id="delete_user",
               responses=_MANAGE_RESPONSES)
def delete_user(user_id: str, request: Request, db: Session = Depends(get_db)):
    """Admins only. Refused while they own a repository: the message lists each, to be given a new owner first. The
    activity record keeps their name against everything they did. Never yourself, nor the last admin."""
    user = _user(db, user_id)
    try:
        management.delete(db, user, request.state.actor)
    except service.Refused as refused:
        db.rollback()
        raise error(409, refused.message, code=refused.code) from None
    db.commit()


@router.delete("/users/{user_id}/machines/{hostname}", response_model=UserOut,
               summary="Remove one machine from a user's registration", operation_id="remove_user_machine",
               responses=_MANAGE_RESPONSES)
def remove_user_machine(user_id: str, hostname: str, request: Request, db: Session = Depends(get_db)):
    """Admins only. Their sessions on that machine end. Their only machine stays: disable them instead."""
    user = _user(db, user_id)
    try:
        management.remove_machine(db, user, request.state.actor, hostname)
    except service.Refused as refused:
        db.rollback()
        raise error(404 if refused.code == "NOT_FOUND" else 409, refused.message, code=refused.code) from None
    db.commit()
    return _out(db, user)


@router.post("/users/{user_id}/reset-password", response_model=UserOut, summary="Reset a user's password",
             operation_id="reset_user_password", responses={404: {"model": ErrorResponse, "description": "No such user."}})
def reset_password(user_id: str, payload: ResetIn, db: Session = Depends(get_db)):
    """Admins only. The temporary password works once: the user sets a new one at their next sign-in. Their sessions
    end."""
    user = _user(db, user_id)
    try:
        service.reset_password(db, user, payload.temporary_password)
    except service.Refused as refused:
        raise _refused(refused) from None
    db.commit()
    return _out(db, user)


class AccessRequestOut(BaseModel):
    id: str
    kind: str = Field(description="'access': to be registered; 'machine': to add a machine to a registration.")
    status: str = Field(description="pending, approved or rejected.")
    name: str
    login: str = Field(description="The name they sign in with once approved.")
    windows_account: str = Field(description="As their platform runs, taken from their machine: never typed.")
    hostname: str = Field(description="Their machine, taken from it: never typed.")
    reason: str | None
    requested_at: datetime.datetime
    decided_at: datetime.datetime | None
    decided_by: str | None


class RejectIn(BaseModel):
    reason: str | None = Field(default=None, description="Optional: shown to the requester on their sign-in page.")


def _request_out(db: Session, row: models.AccessRequest) -> AccessRequestOut:
    decider = db.get(models.User, row.decided_by_user_id) if row.decided_by_user_id else None
    return AccessRequestOut(id=str(row.id), kind=row.kind, status=row.status, name=row.name, login=row.login,
                            windows_account=row.windows_account, hostname=row.hostname, reason=row.reason,
                            requested_at=row.requested_at, decided_at=row.decided_at,
                            decided_by=decider.name if decider else None)


def _access_request(db: Session, request_id: str) -> models.AccessRequest:
    try:
        row = db.get(models.AccessRequest, uuid.UUID(request_id))
    except ValueError:
        row = None
    if row is None:
        raise error(404, f"No access request '{request_id}'", code="NOT_FOUND")
    return row


def _admin(request: Request):
    person = request.state.actor
    if not person.is_admin:
        raise error(403, "Only an admin sees access requests.", code="NOT_ALLOWED")
    return person


@router.get("/access-requests", response_model=list[AccessRequestOut], summary="Access requests, newest first",
            operation_id="list_access_requests")
def list_access_requests(request: Request, status: str | None = Query(None, pattern="^(pending|approved|rejected)$"),
                         db: Session = Depends(get_db)):
    """Admins only. Pending first, then the rest, newest first."""
    _admin(request)
    query = db.query(models.AccessRequest)
    if status:
        query = query.filter(models.AccessRequest.status == status)
    rows = query.order_by((models.AccessRequest.status != "pending"), models.AccessRequest.requested_at.desc()).all()
    return [_request_out(db, r) for r in rows]


@router.post("/access-requests/{request_id}/approve", response_model=AccessRequestOut,
             summary="Approve an access request: always as a developer", operation_id="approve_access_request",
             responses={404: {"model": ErrorResponse, "description": "No such request."},
                        409: {"model": ErrorResponse, "description": "Decided already, or its account is registered."}})
def approve_access_request(request_id: str, request: Request, db: Session = Depends(get_db)):
    """Admins only. Registers them as a developer, with the password they chose, or adds the machine to their
    registration. Making someone an admin is promote's, a separate action."""
    row = _access_request(db, request_id)
    try:
        requests.approve(db, row, request.state.actor)
    except service.Refused as refused:
        db.rollback()
        raise error(409, refused.message, code=refused.code) from None
    db.commit()
    return _request_out(db, row)


@router.post("/access-requests/{request_id}/reject", response_model=AccessRequestOut, summary="Reject an access request",
             operation_id="reject_access_request",
             responses={404: {"model": ErrorResponse, "description": "No such request."},
                        409: {"model": ErrorResponse, "description": "Decided already."}})
def reject_access_request(request_id: str, payload: RejectIn, request: Request, db: Session = Depends(get_db)):
    """Admins only. The reason, if given, is shown on the requester's sign-in page. They may ask again."""
    row = _access_request(db, request_id)
    try:
        requests.reject(db, row, request.state.actor, payload.reason)
    except service.Refused as refused:
        db.rollback()
        raise error(409, refused.message, code=refused.code) from None
    db.commit()
    return _request_out(db, row)


@router.post("/users/{user_id}/promote", response_model=UserOut, summary="Make a user an admin",
             operation_id="promote_user",
             responses={404: {"model": ErrorResponse, "description": "No such user."},
                        409: {"model": ErrorResponse, "description": "An admin already, or deactivated."}})
def promote_user(user_id: str, request: Request, db: Session = Depends(get_db)):
    """Admins only: the one way anyone but the first admin becomes an admin, recorded with who did it."""
    user = _user(db, user_id)
    try:
        requests.promote(db, user, request.state.actor)
    except service.Refused as refused:
        db.rollback()
        raise error(409, refused.message, code=refused.code) from None
    db.commit()
    return _out(db, user)


@router.get("/platform/online", response_model=list[OnlineOut], summary="Who is online, and on which machine",
            operation_id="list_online")
def list_online(db: Session = Depends(get_db)):
    """Each machine with a running backend (a heartbeat fresh within 90 s), with the person signed in there."""
    return [OnlineOut(**entry) for entry in heartbeat.online(db)]


@router.put("/repositories/{repository_id}/owner", response_model=OwnerOut, summary="Assign a repository's owner",
            operation_id="assign_repository_owner",
            responses={404: {"model": ErrorResponse, "description": "No such repository or user."}})
def assign_owner(repository_id: uuid.UUID, payload: OwnerIn, db: Session = Depends(get_db)):
    """Admins only. The owner (with any admin) is the only one who may rescan it, prepare and verify its conversions,
    or delete it. A repository registered before sign-in existed has none until one is assigned here or with
    `python -m app.users assign-owner`."""
    repository = db.get(models.Repository, repository_id)
    if repository is None:
        raise error(404, f"No repository '{repository_id}'", code="NOT_FOUND")
    owner = _user(db, payload.owner_user_id) if payload.owner_user_id else None
    repository.owner_user_id = owner.id if owner else None
    db.commit()
    return OwnerOut(repository_id=str(repository.id), owner_user_id=str(owner.id) if owner else None,
                    owner_name=owner.name if owner else None)


@router.get("/activity", response_model=list[ActivityOut], summary="Who did what, from which machine",
            operation_id="list_activity")
def list_activity(subject_type: str | None = Query(None), subject_id: str | None = Query(None),
                  limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    """Newest first. With subject_type and subject_id: one record's history. Actions from before sign-in existed show
    the actor 'before sign-in'."""
    query = db.query(models.ActivityRecord)
    if subject_type:
        query = query.filter(models.ActivityRecord.subject_type == subject_type)
    if subject_id:
        query = query.filter(models.ActivityRecord.subject_id == subject_id)
    rows = query.order_by(models.ActivityRecord.at.desc(), models.ActivityRecord.id.desc()).limit(limit).all()
    return [ActivityOut(at=r.at, actor=r.actor, hostname=r.hostname, action=r.action, subject_type=r.subject_type,
                        subject_id=r.subject_id, summary=r.summary) for r in rows]

