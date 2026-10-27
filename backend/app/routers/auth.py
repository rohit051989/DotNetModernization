"""Signing in and out, the signed-in person, and asking for access (app.auth). The session is an HttpOnly cookie."""
import datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.auth import activity, machine, requests, service
from app.auth import actor as actors
from app.db import get_db
from app.errors import ErrorResponse, error

router = APIRouter(prefix="/api/auth", tags=["Sign-in"])


class MachineOut(BaseModel):
    windows_account: str = Field(description="The Windows account this platform's backend runs under.")
    hostname: str = Field(description="This machine's name.")
    first_admin_needed: bool = Field(description="True until the first admin is created (python -m app.users create-first-admin).")
    registration: str = Field(default="none", description="This Windows account's registration: 'none', 'other_machines' "
                                                          "(registered, but not for this machine) or 'this_machine'.")


class SignInIn(BaseModel):
    login: str = Field(min_length=1)
    password: str = Field(min_length=1)
    new_password: str | None = Field(default=None, description="Only when the password was set by an admin: the new one.")


class MeOut(BaseModel):
    id: str
    login: str
    name: str
    role: str
    windows_account: str
    hostname: str = Field(description="The machine this session is on.")
    hosts: list[str] = Field(description="Every machine this user may sign in from.")
    must_change_password: bool
    pending_access_requests: int | None = Field(default=None, description="For an admin: access requests waiting for "
                                                                          "a decision. Null for anyone else.")


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


def _me(db: Session, user, host: str) -> MeOut:
    return MeOut(id=str(user.id), login=user.login, name=user.name, role=user.role, windows_account=user.windows_account,
                 hostname=host, hosts=service.hosts(db, user), must_change_password=user.must_change_password,
                 pending_access_requests=requests.pending_count(db) if user.role == actors.ADMIN else None)


class AccessRequestIn(BaseModel):
    name: str = Field(default="", description="Your full name. Not needed to add a machine to your registration.")
    password: str = Field(min_length=1, description="The password you choose; to add a machine, your current one.")


class AccessRequestStatusOut(BaseModel):
    kind: str = Field(description="'access': to be registered; 'machine': to add this machine to a registration.")
    status: str = Field(description="pending, approved or rejected.")
    login: str = Field(description="The name to sign in with once approved.")
    hostname: str
    reason: str | None = Field(description="Why it was rejected, when the admin said.")
    requested_at: datetime.datetime
    decided_at: datetime.datetime | None


def _status(row) -> AccessRequestStatusOut:
    return AccessRequestStatusOut(kind=row.kind, status=row.status, login=row.login, hostname=row.hostname,
                                  reason=row.reason, requested_at=row.requested_at, decided_at=row.decided_at)


@router.get("/access-request", response_model=AccessRequestStatusOut | None,
            summary="How this machine's access request stands", operation_id="get_access_request_status")
def get_access_request(db: Session = Depends(get_db)):
    """Open without a session: the newest request from this platform's Windows account (for access, or to add this
    machine), so the sign-in page can say it is pending, or that it was rejected and why. Null when there is none."""
    row = requests.latest(db, machine.windows_account(), machine.hostname())
    return _status(row) if row is not None else None


@router.post("/access-request", response_model=AccessRequestStatusOut, status_code=201,
             summary="Ask for access from this machine", operation_id="request_access",
             responses={409: {"model": ErrorResponse, "description": "A request is pending already, or there is nothing to "
                                                                     "ask for (registered for this machine; no admin yet)."},
                        401: {"model": ErrorResponse, "description": "To add this machine: the password is wrong."},
                        422: {"model": ErrorResponse, "description": "The name is missing or the password too weak."}})
def request_access(payload: AccessRequestIn, db: Session = Depends(get_db)):
    """Open without a session. The Windows account and the machine are this platform's, never typed. Someone not
    registered gives their name and chooses a password; a registered user on a machine their registration does not
    name gives their password, to have it added. An admin approves or rejects it; approval grants the developer role."""
    try:
        row = requests.request_access(db, name=payload.name, password=payload.password,
                                      account=machine.windows_account(), host=machine.hostname())
    except service.Refused as refused:
        db.rollback()
        status = 401 if refused.code == "WRONG_PASSWORD" else 422 if refused.code in ("WEAK_PASSWORD", "INVALID_USER", "INVALID_ACCOUNT") else 409
        raise error(status, refused.message, code=refused.code) from None
    db.commit()
    return _status(row)


@router.get("/machine", response_model=MachineOut, summary="This machine and the account the platform runs under",
            operation_id="get_auth_machine")
def get_machine(db: Session = Depends(get_db)):
    """Open without a session: the sign-in page shows who and where the person is signing in."""
    account, host = machine.windows_account(), machine.hostname()
    user = service.by_account(db, account)
    registration = "none" if user is None or user.deactivated_at is not None else \
        "this_machine" if any(machine.same(h, host) for h in service.hosts(db, user)) else "other_machines"
    return MachineOut(windows_account=account, hostname=host, first_admin_needed=not service.admins_exist(db),
                      registration=registration)


@router.post("/sign-in", response_model=MeOut, summary="Sign in", operation_id="sign_in",
             responses={401: {"model": ErrorResponse, "description": "Wrong name or password, or not registered for this "
                                                                     "Windows account or machine."},
                        409: {"model": ErrorResponse, "description": "PASSWORD_CHANGE_REQUIRED: send new_password too."}})
def sign_in(payload: SignInIn, response: Response, db: Session = Depends(get_db)):
    """The password, the Windows account this backend runs under, and this machine must all match the user's
    registration. Sets the session cookie (HttpOnly). This deters shared credentials; it is not a hard security
    boundary, since the platform runs on the user's own machine."""
    try:
        token, user = service.sign_in(db, payload.login, payload.password, payload.new_password)
    except service.Refused as refused:
        db.commit()
        status = 409 if refused.code == "PASSWORD_CHANGE_REQUIRED" else 422 if refused.code in ("WEAK_PASSWORD", "SAME_PASSWORD") else 401
        raise error(status, refused.message, code=refused.code) from None
    host = machine.hostname()
    activity.record(db, "sign_in", "user", str(user.id), "Signed in", actor=actors.of(user, host))
    db.commit()
    response.set_cookie(service.COOKIE, token, httponly=True, samesite="lax", path="/")
    return _me(db, user, host)


@router.post("/sign-out", status_code=204, summary="Sign out", operation_id="sign_out")
def sign_out(request: Request, response: Response, db: Session = Depends(get_db)):
    service.sign_out(db, request.cookies.get(service.COOKIE))
    db.commit()
    response.delete_cookie(service.COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=MeOut, summary="The signed-in person", operation_id="get_me")
def get_me(request: Request, db: Session = Depends(get_db)):
    person = request.state.actor
    user = db.get(models.User, person.user_id)
    return _me(db, user, person.hostname)


@router.post("/password", status_code=204, summary="Change your own password", operation_id="change_password",
             responses={422: {"model": ErrorResponse, "description": "The current password is wrong, or the new one too weak."}})
def change_password(payload: PasswordIn, request: Request, db: Session = Depends(get_db)):
    person = request.state.actor
    user = db.get(models.User, person.user_id)
    try:
        service.change_password(db, user, payload.current_password, payload.new_password)
    except service.Refused as refused:
        raise error(422, refused.message, code=refused.code) from None
    activity.record(db, "change_password", "user", str(user.id), "Changed their password", actor=person)
    db.commit()
    return Response(status_code=204)
