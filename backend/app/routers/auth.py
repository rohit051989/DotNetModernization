"""Signing in and out, and the signed-in person (app.auth). The session is an HttpOnly cookie."""
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.auth import activity, machine, service
from app.auth import actor as actors
from app.db import get_db
from app.errors import ErrorResponse, error

router = APIRouter(prefix="/api/auth", tags=["Sign-in"])


class MachineOut(BaseModel):
    windows_account: str = Field(description="The Windows account this platform's backend runs under.")
    hostname: str = Field(description="This machine's name.")
    first_admin_needed: bool = Field(description="True until the first admin is created (python -m app.users create-first-admin).")


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


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


def _me(db: Session, user, host: str) -> MeOut:
    return MeOut(id=str(user.id), login=user.login, name=user.name, role=user.role, windows_account=user.windows_account,
                 hostname=host, hosts=service.hosts(db, user), must_change_password=user.must_change_password)


@router.get("/machine", response_model=MachineOut, summary="This machine and the account the platform runs under",
            operation_id="get_auth_machine")
def get_machine(db: Session = Depends(get_db)):
    """Open without a session: the sign-in page shows who and where the person is signing in."""
    return MachineOut(windows_account=machine.windows_account(), hostname=machine.hostname(),
                      first_admin_needed=not service.admins_exist(db))


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
