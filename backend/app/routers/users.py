"""Users (admins only, by app.auth.policy: every change here is an admin's), who is online, repository owners, and
the activity record."""
import datetime
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import heartbeat, models
from app.auth import service
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
    role: str = Field(description="'admin' or 'developer'.")
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
    """Admins only. The temporary password works once: the user sets their own at the first sign-in."""
    try:
        user = service.create_user(db, login=payload.login, name=payload.name, windows_account=payload.windows_account,
                                   role=payload.role, host_names=payload.hosts, password=payload.temporary_password)
    except service.Refused as refused:
        raise _refused(refused) from None
    db.commit()
    return _out(db, user)


@router.put("/users/{user_id}", response_model=UserOut, summary="Change a user", operation_id="update_user",
            responses={404: {"model": ErrorResponse, "description": "No such user."}})
def update_user(user_id: str, payload: UserUpdate, db: Session = Depends(get_db)):
    """Admins only. Only the fields sent change. Deactivating a user ends their sessions."""
    user = _user(db, user_id)
    try:
        service.update_user(db, user, name=payload.name, role=payload.role, windows_account=payload.windows_account,
                            host_names=payload.hosts, active=payload.active)
    except service.Refused as refused:
        raise _refused(refused) from None
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

